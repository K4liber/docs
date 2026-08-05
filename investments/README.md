# Investments

## Passive Investing

Most of my investments are in the form of S&P 500 index fund. Justification: If ever the US economy is going to collapse, it will be a global collapse. So I might as well invest in the US economy. Such a collapse would be a whole capitalist collapse. The S&P 500 index fund is a good way to invest in the US economy without having to pick individual stocks. Its a type of passive investing. I just do not buy if the market is too high. I tend to buy when it is at least 5-10% lower than the last peak.

## Active Investing

Using IKE&IKZE accounts, I can invest in individual stocks without paying taxes on the profits. The idea is to analyze TOP100 (by capitalization) tech companies (https://companiesmarketcap.com/tech/largest-tech-companies-by-market-cap/) and TOP100 energy companies (https://companiesmarketcap.com/energy/largest-companies-by-market-cap/) and pick a single one that is undervalued. I am going to invest only in one stock at a time. Always the full amount on IKE&IKZE accounts. The bet is that the stock will go up by 10% (even if it goes up by 5%, but in a one or few days, its ok to sell it since annualized return in such a case is significant). The exit strategy is the stock being down by 10%. I will use the following criteria to pick a stock:

- Products and services subjective value (judged by me, I need to believe in the company)
- Historical stock price trends, especially if company is down and undervalued. This means a high probability of 10% increase comparing to the decrease.
- Price-to-Earnings (P/E) ratio
- Price-to-Book (P/B) ratio
- Revenue growth
- Profit margins

I need to create a CSV file with the data of the TOP100 tech and TOP100 energy companies and their financial data. I will use this data to analyze and pick a stock. Such a csv should contain the following columns:
- Sector (tech or energy)
- Company Name
- Market Cap
- P/E Ratio
- P/B Ratio
- Revenue Growth
- Profit Margin
- Products and services
- Products and services score (manually provided by me, if not provided, all companies will have the same score)
- Undervalued score (some simple heuristic based on current stock price and historical trends)
- The Volatility score (some simple heuristic based on historical stock price trends) that will increase the change of 10% increase in a lower amount of time. The higher the volatility, the higher the chance of 10% increase in a lower amount of time.

Then we should have a script that reads this CSV file and create another rank.csv which contains only the companies that meet my criteria for investment. Each column should be weighted based on some assumptions. The rank.csv should contain the following columns:
- Ticker
- Company Name
- Sector
- Weighted Score (calculated based on the weighted sum of the criteria)
- Valuation Score
- Fundamentals Score
- Undervalued Score
- Volatility Score
- Rebound From Low

The rank.csv should actually contain a date of producing the results, because the rank will change over time. So the output file name should be rank_YYYY-MM-DD.csv.

### Automation

The automation is a Python package managed entirely by [uv](https://docs.astral.sh/uv/). It
uses CompaniesMarketCap for the top-100 tech and top-100 energy universe, and Yahoo Finance's public quote pages for
fundamentals and one year of adjusted closing prices.

From this directory, install the locked environment and run the complete workflow:

```shell
uv sync
uv run active-investing run
```

The command refreshes `data/companies.csv` and creates `data/rank_YYYY-MM-DD.csv`. The stages
can also be run independently:

```shell
uv run active-investing collect
uv run active-investing rank
```

Use `uv run active-investing --help` or append `--help` after a subcommand for all options.
For example, `collect --workers 1` reduces request concurrency if a data provider rate-limits
requests.

If fewer than half of the companies return complete provider data, collection fails without
replacing the existing CSV. This prevents a temporary provider outage from destroying a usable
dataset.

#### Manual fields

Edit `Products and services` and `Products and services score` directly in
`data/companies.csv`. A later `collect` or `run` preserves both fields by ticker. New companies
receive a product score of 50 by default; this can be changed with
`--default-products-score`. Scores must be between 0 and 100.

`Revenue Growth`, `Profit Margin`, and `Annualized Volatility` are decimal fractions, so `0.15`
means 15%. `Market Cap` is an integer number of US dollars from CompaniesMarketCap.

#### Ranking assumptions

Weights and eligibility filters are editable in `ranking.toml`. By default, a company must
have complete metrics, positive P/E and P/B ratios, non-negative revenue growth and profit
margin, a product score of at least 50, and a rebound of at least 5% above its 52-week low.
P/E and P/B are scored lower-is-better; revenue growth and profit margin are scored
higher-is-better using percentile ranks among eligible companies within the same sector.
The three explicit scores already use a 0-100 scale.

The undervalued heuristic combines the drawdown from the one-year high with the current
position in the one-year price range. A 30% drawdown saturates its drawdown component. The
volatility heuristic annualizes the standard deviation of daily returns; it maps 15% or less
to 0 and 60% or more to 100. These heuristics describe historical prices and do not predict a
future 10% gain.

Run the quality checks with:

```shell
uv run ruff check .
uv run pytest
uv run pip-audit
```

This output is a research screen, not investment advice. Provider data can be delayed,
missing, or incorrect, and a stop-loss order does not guarantee execution at its trigger
price.