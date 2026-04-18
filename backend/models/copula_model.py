"""
t-Copula + GARCH(1,1) Tail Dependence Model.

Detects correlation breakdown and cross-asset contagion that Pearson
correlation misses. During a crisis, tail dependence rises sharply even
when bulk linear correlation appears stable.

Pipeline:
    1. Per-segment GARCH(1,1) to capture volatility clustering.
    2. Standardized residuals → empirical marginal CDF (rank transform).
    3. t-copula fit: estimate ν (degrees of freedom) via profile MLE on
       a coarse grid. Copula parameter ρ from Kendall's τ.
    4. Lower-tail dependence coefficient:
           λ_L(i,j) = 2 * t_{ν+1}( -sqrt((ν+1)*(1-ρ)/(1+ρ)) )
    5. Joint-crash probability via copula CDF at the 1% quantile.

All computation is NumPy/SciPy; no extra deps. Safe defaults for warm-up.
"""
import numpy as np
from scipy.stats import t as student_t, kendalltau, norm
from collections import deque
from typing import Dict, List, Optional, Tuple


class GARCH11:
    """Minimal GARCH(1,1) volatility estimator.

    σ_t² = ω + α·r_{t-1}² + β·σ_{t-1}²

    Uses fast closed-form moment estimates rather than full MLE to stay
    under 1 ms per update; good enough for real-time filtering of
    vol-clustered returns into i.i.d. standardized residuals.
    """

    def __init__(self, window: int = 400):
        self.window = window
        self._returns: deque = deque(maxlen=window)
        # Industry-typical GARCH(1,1) parameters for equity returns
        self.omega = 1e-6
        self.alpha = 0.08
        self.beta = 0.90
        self._var = 1e-4
        self._fitted = False

    def update(self, ret: float) -> float:
        """Feed a new return, return current conditional variance."""
        if not np.isfinite(ret):
            return self._var
        self._returns.append(float(ret))
        if len(self._returns) >= 30 and not self._fitted:
            self._calibrate()
            self._fitted = True
        # GARCH recursion
        self._var = self.omega + self.alpha * ret * ret + self.beta * self._var
        self._var = max(self._var, 1e-10)
        return self._var

    def _calibrate(self):
        """Coarse moment-match calibration of ω given fixed α + β."""
        r = np.array(self._returns, dtype=np.float64)
        r = r[np.isfinite(r)]
        if len(r) < 20:
            return
        long_run_var = float(np.var(r))
        if long_run_var <= 0:
            return
        # LR var = ω / (1 - α - β)
        persistence = self.alpha + self.beta
        if persistence >= 0.999:
            persistence = 0.98
        self.omega = long_run_var * (1.0 - persistence)
        self._var = long_run_var

    def sigma(self) -> float:
        return float(np.sqrt(max(self._var, 1e-10)))

    def standardize(self, ret: float) -> float:
        """Return standardized residual z_t = r_t / σ_t."""
        s = self.sigma()
        return float(ret / s) if s > 1e-10 else 0.0


class TCopulaTailDependence:
    """t-copula + GARCH(1,1) tail dependence estimator.

    Operates on market *segments* rather than individual assets to keep
    the correlation matrix small (5×5) and the copula fit cheap.

    Segments mirror CISS: equities, forex, spreads, credit, volatility.
    """

    SEGMENTS = ["equities", "forex", "spreads", "credit", "volatility"]

    # Which tickers contribute to which segment.  Missing tickers are
    # silently skipped, so the model degrades cleanly to a subset.
    SEGMENT_TICKERS: Dict[str, List[str]] = {
        "equities":   ["SPY", "QQQ", "DIA", "IWM", "XLF"],
        "forex":      ["EURUSD", "GBPUSD", "USDJPY"],
        "spreads":    ["SPY", "QQQ", "JPM", "GS", "BAC"],  # spread-derived returns
        "credit":     ["JPM", "GS", "BAC", "C", "MS"],
        "volatility": ["BTCUSD", "ETHUSD"],
    }

    def __init__(self, window: int = 500):
        self.window = window
        self._garch: Dict[str, GARCH11] = {seg: GARCH11(window) for seg in self.SEGMENTS}
        self._residuals: Dict[str, deque] = {seg: deque(maxlen=window) for seg in self.SEGMENTS}
        self._nu: float = 8.0  # t-copula degrees of freedom (will be fit)
        self._rho: np.ndarray = np.eye(len(self.SEGMENTS))
        self._lambda_L: np.ndarray = np.zeros((len(self.SEGMENTS), len(self.SEGMENTS)))
        self._warm: bool = False
        self._update_counter: int = 0

    # ── public API ──────────────────────────────────────────────────
    def update(self, tick_assets: dict) -> Dict:
        """Feed a tick; return current tail-dependence snapshot."""
        # 1. Compute a synthetic segment return as equal-weighted average
        segment_returns = self._segment_returns(tick_assets)

        # 2. Push through per-segment GARCH → standardized residual
        for seg, r in segment_returns.items():
            if r is None:
                continue
            self._garch[seg].update(r)
            z = self._garch[seg].standardize(r)
            if np.isfinite(z):
                self._residuals[seg].append(z)

        # 3. Need minimum data to fit copula
        min_len = min(len(self._residuals[s]) for s in self.SEGMENTS)
        if min_len < 50:
            return self._snapshot(warmup=True, observations=min_len)

        # 4-7: Heavy copula fitting (kendalltau + MLE + matrix ops)
        # Only recompute every 10 ticks — results are stable tick-to-tick
        self._update_counter += 1
        if self._update_counter % 10 == 1 or not self._warm:
            U = self._pseudo_observations(min_len)
            self._rho = self._kendall_rho(U)
            self._nu = self._fit_nu(U, self._rho)
            self._lambda_L = self._tail_dependence_matrix(self._rho, self._nu)
            self._warm = True

        return self._snapshot(warmup=False, observations=min_len)

    def joint_crash_probability(self, quantile: float = 0.01) -> float:
        """P(all segments below their `quantile` quantile simultaneously)."""
        if not self._warm:
            return 0.0
        n = len(self.SEGMENTS)
        # Lower-tail: P(U_i <= q for all i) ≈ determined by copula C_t(q,...,q)
        # Closed form is intractable; use average pairwise λ_L as proxy:
        triu_idx = np.triu_indices(n, k=1)
        lam = self._lambda_L[triu_idx]
        avg_lam = float(np.mean(lam)) if lam.size > 0 else 0.0
        # Heuristic upper bound for joint-crash prob given pairwise λ_L
        # P_joint ≈ q * avg_λ_L  (monotone in both)
        return float(np.clip(quantile * (1.0 + avg_lam * (n - 1)), 0.0, 1.0))

    def get_snapshot(self) -> Dict:
        return self._snapshot(warmup=not self._warm, observations=self._min_obs())

    # ── internals ───────────────────────────────────────────────────
    def _min_obs(self) -> int:
        return min(len(self._residuals[s]) for s in self.SEGMENTS)

    def _segment_returns(self, assets: dict) -> Dict[str, Optional[float]]:
        """Equal-weighted log return across each segment's tickers."""
        out: Dict[str, Optional[float]] = {}
        for seg, tickers in self.SEGMENT_TICKERS.items():
            vals = []
            for t in tickers:
                a = assets.get(t)
                if not a:
                    continue
                pct = a.get("pct_change")
                if pct is None or not np.isfinite(pct):
                    continue
                vals.append(pct / 100.0)  # pct_change is in %, convert to decimal
            out[seg] = float(np.mean(vals)) if vals else None
        return out

    def _pseudo_observations(self, n: int) -> np.ndarray:
        """Rank-transform each segment's residuals to (0,1)."""
        cols = []
        for seg in self.SEGMENTS:
            r = np.array(list(self._residuals[seg])[-n:], dtype=np.float64)
            # Rank / (n+1) to keep strictly in (0,1)
            ranks = r.argsort().argsort() + 1
            u = ranks / (n + 1.0)
            cols.append(u)
        return np.column_stack(cols)

    @staticmethod
    def _kendall_rho(U: np.ndarray) -> np.ndarray:
        """Correlation matrix for t-copula via Kendall's τ.
        ρ = sin(π·τ/2)
        """
        n_seg = U.shape[1]
        rho = np.eye(n_seg)
        for i in range(n_seg):
            for j in range(i + 1, n_seg):
                try:
                    tau, _ = kendalltau(U[:, i], U[:, j])
                    if not np.isfinite(tau):
                        tau = 0.0
                except Exception:
                    tau = 0.0
                r = float(np.sin(np.pi * tau / 2.0))
                r = float(np.clip(r, -0.999, 0.999))
                rho[i, j] = rho[j, i] = r
        # PSD projection
        rho = TCopulaTailDependence._project_psd(rho)
        return rho

    @staticmethod
    def _project_psd(M: np.ndarray) -> np.ndarray:
        """Project symmetric matrix to nearest PSD with unit diagonal."""
        try:
            eigvals, eigvecs = np.linalg.eigh(M)
            eigvals = np.maximum(eigvals, 1e-6)
            M = eigvecs @ np.diag(eigvals) @ eigvecs.T
            d = np.sqrt(np.diag(M))
            d = np.where(d <= 0, 1.0, d)
            M = M / np.outer(d, d)
            np.fill_diagonal(M, 1.0)
            return M
        except Exception:
            return np.eye(M.shape[0])

    @staticmethod
    def _fit_nu(U: np.ndarray, rho: np.ndarray) -> float:
        """Profile log-likelihood over a coarse grid of ν."""
        # Transform pseudo-obs through t-quantile for candidate ν
        n, d = U.shape
        try:
            rho_inv = np.linalg.inv(rho)
            sign, logdet = np.linalg.slogdet(rho)
            if sign <= 0:
                return 8.0
        except np.linalg.LinAlgError:
            return 8.0

        best_nu = 8.0
        best_ll = -np.inf
        # Coarse grid; enough for real-time use
        for nu in (3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 25.0, 50.0):
            try:
                T = student_t.ppf(U, df=nu)
                # guard against ±inf at boundaries
                if not np.all(np.isfinite(T)):
                    T = np.nan_to_num(T, nan=0.0, posinf=5.0, neginf=-5.0)
                quad = np.einsum("ij,jk,ik->i", T, rho_inv, T)
                # log-density of multivariate-t copula (up to constants that drop out)
                # ll = sum( log c_t(u) )
                term1 = -0.5 * logdet * n
                term2 = -((nu + d) / 2.0) * np.sum(np.log1p(quad / nu))
                term3 = +((nu + 1) / 2.0) * np.sum(np.log1p(T ** 2 / nu))
                ll = term1 + term2 + term3
                if ll > best_ll and np.isfinite(ll):
                    best_ll = ll
                    best_nu = nu
            except Exception:
                continue
        return float(best_nu)

    @staticmethod
    def _tail_dependence_matrix(rho: np.ndarray, nu: float) -> np.ndarray:
        """λ_L(i,j) = 2·F_{ν+1}( -sqrt((ν+1)·(1-ρ)/(1+ρ)) )"""
        n = rho.shape[0]
        L = np.zeros_like(rho)
        for i in range(n):
            for j in range(n):
                if i == j:
                    L[i, j] = 1.0
                    continue
                r = float(rho[i, j])
                r = float(np.clip(r, -0.999, 0.999))
                arg = -np.sqrt(max(0.0, (nu + 1.0) * (1.0 - r) / (1.0 + r)))
                lam = 2.0 * student_t.cdf(arg, df=nu + 1)
                L[i, j] = float(np.clip(lam, 0.0, 1.0))
        return L

    def _snapshot(self, warmup: bool, observations: int) -> Dict:
        n = len(self.SEGMENTS)
        triu = np.triu_indices(n, k=1)
        avg_lam = float(np.mean(self._lambda_L[triu])) if self._warm else 0.0
        max_lam = float(np.max(self._lambda_L[triu])) if self._warm else 0.0
        if self._warm:
            argmax = int(np.argmax(self._lambda_L[triu]))
            i_idx = triu[0][argmax]
            j_idx = triu[1][argmax]
            hot_pair = (self.SEGMENTS[i_idx], self.SEGMENTS[j_idx])
        else:
            hot_pair = None
        return {
            "warmup": warmup,
            "observations": int(observations),
            "nu": round(float(self._nu), 2),
            "segments": self.SEGMENTS,
            "correlation_matrix": np.round(self._rho, 4).tolist(),
            "tail_dependence_matrix": np.round(self._lambda_L, 4).tolist(),
            "avg_tail_dependence": round(avg_lam, 4),
            "max_tail_dependence": round(max_lam, 4),
            "hot_pair": list(hot_pair) if hot_pair else None,
            "joint_crash_prob_1pct": round(self.joint_crash_probability(0.01), 6),
        }


# Singleton
copula_model = TCopulaTailDependence()
