# Crop Price Watch — NOTES

Student project: Crop Price Watch
Region: Punjab, Pakistan
Crops: Garlic (Local), Carrot, and Peas
Collection dates: 22, 23, and 24 November 2026
Currency for comparison: Pakistani Rupees per kilogram (PKR/kg)

## 1. Project aim

I collected public vegetable wholesale prices to help compare crops and markets. The Tableau dashboard answers these questions: which crop is most expensive; which crop changes most across three days; and whether markets report different prices for the same crop.

## 2. Data sources

I used two public websites:

- MandiOye: https://mandioye.com/amis/commodity/garlic-local (and the matching /carrot and /peas pages).
- PakDataHub: https://pakdatahub.com/mandi/garlic_local (and the matching /carrot and /peas pages).

I collected public crop and market information only. I did not log in or collect personal data. MandiOye reports an FQP wholesale price in PKR per 100 kg. PakDataHub reports prices in PKR per kg. The `date` field is the published price date, not the date when I downloaded the page.

## 3. Web scraping and snapshots

I used Python, Requests, BeautifulSoup, and Pandas in Google Colab. The scraper checks robots.txt, waits between requests, follows MandiOye Next-page links, and handles HTTP failures. It saves the original source URL for each record. The independent `scraper.py` is an organized version of this process.

I ran the scraper on three different collection days and kept a separate real timestamped CSV for each run:

- 22 November: 354 raw records (120 MandiOye, 234 PakDataHub).
- 23 November: 447 raw records (199 MandiOye, 248 PakDataHub).
- 24 November: 430 raw records (196 MandiOye, 234 PakDataHub).

Total: 1,231 raw observations across three collection runs. Some PakDataHub observations had older published price dates. A record collected on 24 November is not necessarily a price published on 24 November.

## 4. Raw fields and data types

- crop: text (String), for example Garlic.
- market: text (String), the reporting mandi or market name.
- date: date (Date in YYYY-MM-DD), the published market-price date.
- price: decimal number (Float), the price in the source's original unit.
- unit: text (String), originally PKR/100kg or PKR/kg.
- price_per_kg: decimal number (Float), converted price in PKR/kg.
- source_url: text (String/URL), the public source page.
- scraped_at: timezone-aware datetime (Datetime/String in the CSV), when the scraper collected the record in Pakistan time.
- source: text (String), mandioye.com or pakdatahub.com.

## 5. Data cleaning

I combined the three real snapshots and selected records with published price dates of 22, 23, and 24 November. I converted numeric and date values, removed invalid or missing key values, and kept only prices above zero. All final prices use PKR/kg: I divided MandiOye PKR/100kg prices by 100, while PakDataHub prices were already PKR/kg.

I normalized crop and market labels, including removing a trailing 'major' label from market names. For duplicated observations of the same crop, market, and published date, I preferred the MandiOye record. Among overlapping sources on 22 November, 11 matched crop–market groups had small price differences (up to 0.50 PKR/kg), likely linked to reporting precision or rounding; I did not average the two source prices. The earlier working clean file contained 527 records. During final validation I found that 'Bahawal Nagar' and 'Bahawalnagar' identified the same market on 22 November in three crop records (Carrot, Garlic, and Peas). Each duplicate had the exact same published price. I kept the MandiOye observation and removed the duplicate PakDataHub copy.

Final clean_data.csv: 524 unique crop–normalized market–date records, all in PKR/kg. There are no missing values in the required fields, no non-positive prices, and no remaining duplicate crop/normalized-market/date keys.

The cleaned fields for delivery are: crop (text), market (text), date (date), price (decimal number, PKR/kg), unit (text), source (text), source_url (text/URL), and scraped_at (datetime).

## 6. Question 1 — Most expensive crop

I compared the mean price of each crop across markets reporting a price for 24 November 2026. Garlic was the most expensive, with an average price of 210.70 PKR/kg. Peas averaged 157.83 PKR/kg and Carrot averaged 60.39 PKR/kg. Tableau displays this as a Bar Chart.

## 7. Question 2 — Price movement over three days

I used MandiOye records for this comparison because PakDataHub did not have new published prices for 23 or 24 November in the supplied snapshots. I kept only crop–market pairs with a valid price on all three published dates. This produced 111 pairs: 39 Carrot, 38 Peas, and 34 Garlic.

For each market and crop, I calculated the absolute percentage change from 22 to 23 November and from 23 to 24 November, added these two percentages, and then averaged the total by crop. This measures cumulative absolute daily movement, NOT the net percentage increase or decrease.

Results: Carrot 6.69% (39 markets), Peas 5.42% (38 markets), Garlic 4.01% (34 markets). Therefore Carrot showed the largest average relative daily price movement. The Q2 Line Chart shows the three-day trends in average prices across those matched markets. The movement percentages are stated separately because line slopes of average prices do not directly show each market's absolute movement.

## 8. Question 3 — Market and website differences

I used a Heatmap for selected markets and a Box Plot for the distribution of prices across available markets, both for 24 November 2026. The Heatmap uses a Tableau calculated field called 'Market Price Difference (%)'. It compares a market's crop price against the average price of the same crop on the same date. Positive values mean above average and negative values mean below average. The Box Plot shows medians, price spread, and outliers in PKR/kg.

The data support a comparison between markets. They do not support a reliable three-day like-for-like comparison of the two websites. The final clean dataset contains 515 MandiOye records and 9 non-overlapping PakDataHub records, all of which from PakDataHub are dated 22 November. Some sources may reflect the same underlying AMIS reporting feed, so their observations should not be treated as independent confirmations.

## 9. Tableau dashboard

I created a packaged Tableau dashboard with four charts: Q1 Bar Chart, Q2 Line Chart, Q3 Heatmap, and Q3 Box Plot. It includes date and market filters, a calculated field, unit labels, and a Key Findings area. The sources and their limitations are documented in these notes. The Heatmap colors show relative market differences; the Box Plot shows original PKR/kg values. The market selector is intended for the Heatmap, while the Box Plot uses the broader available-market distribution.

I kept the Tableau packaged workbook (.twbx) with its embedded CSV data. My final packaged copy uses the cleaned 524-row source. The Q2 dataset still has 333 observations from 111 matched crop–market pairs across 3 days.

## 10. Data limitations

- Collection date and published price date differ, especially for PakDataHub.
- Missing crop–market/date observations were not invented or filled with guessed prices.
- Q2 compares the same markets across 3 days for a fair movement measure; Q1 uses all valid markets on 24 November, so their displayed averages can differ slightly.
- Market labels were standardized. For overlapping source records, the preferred record is from MandiOye.
- Website layout and robots.txt permissions can change. The scraper should be tested again before future collection.
- Prices are observed wholesale quotations, not guaranteed farm-gate sales offers. Farmers should verify locally before decisions.

## 11. AI use

I used ChatGPT as an assistant to understand the assignment, organize and comment Python code, suggest cleaning and validation checks, explain price-movement calculations, and improve Tableau charts and documentation. I reviewed the results against the collected CSV files. The original snapshots came from scraping real public websites; AI did not create or fabricate the prices or collection timestamps.

## 12. Files submitted

The ZIP contains scraper.py, three original timestamped CSV files in snapshots/, clean_data.csv, dashboard.twbx, and this NOTES.md. The cleaned CSV is the one used by the final Tableau packaged workbook.