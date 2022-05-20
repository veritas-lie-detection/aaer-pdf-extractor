# aaer-pdf-extractor
## Extracting Information from AAERs

### Overview
This code takes the information stored in AuroraMySQL by **aaer-table-scraping** and attempts to extract information used to identify investor harm. The information extracted are stored in a DynamoDB with their descriptors below:

| Field | Type | Description |
| :--- | :--- | :--- |
| cik | string | (primary key) The Central Index Key for a company associated with investor harm (according to the [SEC API](https://sec-api.io/)). |
| url | string | (secondary key) The url of the AAER information was extracted from. |
| company name | string | The name of the company associated with investor harm (according to the [SEC API](https://sec-api.io/)). |
| ticker | string | The ticker of the company associated with investor harm (according to the [SEC API](https://sec-api.io/)). |
| itmo_section | string | The introduction section for the AAER. |
| contains_21c | bool | Whether or not the AAER determined significant investor harm. |

### Methodology
