[1] Tabatabaei & Mousavi (2026) — XGBoost + SHAP
https://www.preprints.org/manuscript/202604.0052

Data: S&P 100, 2000–2025, 552K observations
Best model: XGBoost — R² = 0.918, RMSE = 1.906 (22% better than Random Forest)
Finding: Risk drivers shift by regime — debt dominates normally, VIX spikes in GFC, rates dominate in COVID
→ Velure: Validates Merton Model as credit risk target; justifies dynamic ensemble weights


[2] Chohan et al. (2026) — Hybrid CNN-LSTM-GRU
https://www.mdpi.com/2227-9091/14/1/14

Data: 4,750 Chinese firms, quarterly 2015–2023
Best model: Hybrid — 93.5% accuracy, AUC 0.925, F1 0.904 (beats LSTM 90.9%, RF 89.2%, XGBoost 90.3%)
Finding: No single model wins — hybrid outperforms all; GRU converges in 30 epochs vs. LSTM's 160
→ Velure: Validates LSTM for temporal detection; proves ensemble > single model (why we split 35/35/20/10)


[3] Yang et al. (2025) — TVP-FAVAR + Transformer + Sentiment
https://www.mdpi.com/2079-8954/13/8/720

Data: 26 indicators × 7 market sectors, China 2010–2024 + 3M forum posts (FinBERT)
Best model: Transformer — RMSE 0.109, AUC 0.855 (vs. RF: RMSE 0.203, SVM: RMSE 0.177)
Finding: Online panic is a statistically valid leading indicator (BDS p < 0.01); stress only amplifies when multiple markets deteriorate together
→ Velure: Validates CISS (cross-market correlation weighting) and t-Copula (tail contagion across assets)


[4] Beutel, List & von Schweinitz (2018) — ML vs. Logit Benchmark
https://ideas.repec.org/p/zbw/bubdps/482018.html

Data: 15 countries, 22 banking crises, 1970–2016
Key result: Random Forest in-sample Ur = 0.990 → out-of-sample Ur = −0.003 (collapses); Logit holds at 0.605
Finding: ML models systematically overfit on financial crisis data — in-sample accuracy is misleading
→ Velure: Why we use Isolation Forest (unsupervised, no crisis labels needed) + EMA smoothing to prevent the same out-of-sample collapse