-- ============================================
-- Project Velure — Seed Data
-- ============================================

-- Seed: Data Sources
INSERT INTO dim_source (provider_name, api_endpoint, data_frequency, latency_tier) VALUES
('Polygon.io',      'wss://socket.polygon.io',           'TICK',   'LOW'),
('Finnhub',         'wss://ws.finnhub.io',               'TICK',   'LOW'),
('FRED',            'https://api.stlouisfed.org/fred',    'DAILY',  'HIGH'),
('Alpha Vantage',   'https://www.alphavantage.co/query',  '15MIN',  'MED'),
('Simulator',       'internal://stress-test',             'TICK',   'LOW');

-- Seed: Tracked Assets
INSERT INTO dim_asset (ticker, asset_class, asset_name, currency, jurisdiction, sector) VALUES
-- Major Equities
('SPY',   'EQUITY',   'S&P 500 ETF',              'USD', 'US', 'Index'),
('QQQ',   'EQUITY',   'Nasdaq 100 ETF',            'USD', 'US', 'Index'),
('DIA',   'EQUITY',   'Dow Jones ETF',             'USD', 'US', 'Index'),
('IWM',   'EQUITY',   'Russell 2000 ETF',          'USD', 'US', 'Index'),
('XLF',   'EQUITY',   'Financial Sector ETF',      'USD', 'US', 'Financials'),
('JPM',   'EQUITY',   'JPMorgan Chase',            'USD', 'US', 'Financials'),
('GS',    'EQUITY',   'Goldman Sachs',             'USD', 'US', 'Financials'),
('BAC',   'EQUITY',   'Bank of America',           'USD', 'US', 'Financials'),
('C',     'EQUITY',   'Citigroup',                 'USD', 'US', 'Financials'),
('MS',    'EQUITY',   'Morgan Stanley',            'USD', 'US', 'Financials'),
-- Forex
('EURUSD', 'FX', 'Euro/USD',               'USD', 'GLOBAL', 'FX'),
('GBPUSD', 'FX', 'GBP/USD',                'USD', 'GLOBAL', 'FX'),
('USDJPY', 'FX', 'USD/JPY',                'JPY', 'GLOBAL', 'FX'),
-- Rates & Macro
('SOFR',      'RATE', 'Secured Overnight Financing Rate', 'USD', 'US', 'Interbank'),
('TEDSPREAD', 'RATE', 'TED Spread',                       'USD', 'US', 'Credit Risk'),
('STLFSI',    'RATE', 'St. Louis Financial Stress Index',  'USD', 'US', 'Systemic'),
('US10Y',     'BOND', 'US 10-Year Treasury Yield',         'USD', 'US', 'Sovereign'),
('US2Y',      'BOND', 'US 2-Year Treasury Yield',          'USD', 'US', 'Sovereign'),
-- Crypto (high volatility stress signal)
('BTCUSD', 'CRYPTO', 'Bitcoin/USD', 'USD', 'GLOBAL', 'Crypto'),
('ETHUSD', 'CRYPTO', 'Ethereum/USD', 'USD', 'GLOBAL', 'Crypto');
