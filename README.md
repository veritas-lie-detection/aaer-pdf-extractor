# aaer-pdf-extractor
## Extracting Information from AAERs

### Overview
##### Note: Currently scraping information stored in .html domains is not supported.
This code takes the information stored in AuroraMySQL by **aaer-table-scraping** and attempts to extract information used to identify investor harm. The information extracted are stored in a DynamoDB with their descriptors below:

| Field | Type | Description |
| :--- | :--- | :--- |
| cik | string | (primary key) The Central Index Key for a company associated with investor harm (according to the [SEC API](https://sec-api.io/)). |
| url | string | (secondary key) The url of the AAER information was extracted from. |
| company name | string | The name of the company associated with investor harm (according to the [SEC API](https://sec-api.io/)). |
| ticker | string | The ticker of the company associated with investor harm (according to the [SEC API](https://sec-api.io/)). |
| itmo_section | string | The introduction section for the AAER. |
| contains_21c | bool | Whether or not the AAER determined significant investor harm. |
| year_start | int | The year fraudulent activity for the company started (according to the AAER). |
| month_start | int | The month fraudulent activity for the company started. |
| year_end | int | The year fraudulent activity for the company ended. |
| month_end | int | The month fraudulent activity for the company ended. |
| scraped | bool | Whether the 10-Ks of fraud have been collected. |

### Methodology
The most important information to extract from each AAER is the company name along with the start and end date of fraudulent activity. Company names are taken from AAERs by searching for business entity terms (e.g. LLC, CORP, INC). These company names are then fed through fuzzy string matching [SEC API](https://sec-api.io/)) to attain their CIK and ticker. Dates are extracted using Spacy, then filtered to be within 2 standard deviation from the mean (should change to median) to remove outliers.

### Improvements
When multiple companies exist, the script is unable to determine which company each AAER is referring to, thus these documents are skipped. The script is also unable to determine a company given only people names.
