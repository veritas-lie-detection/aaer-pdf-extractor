import boto3
from thefuzz import fuzz
import pdfplumber
import pymysql
from sec_api import QueryApi
import spacy
import urllib3

import io
import os
import time
from typing import Dict, List, Optional, Tuple

from nlp_engine import parse_text


class PDFReader:
    """Extracts relevant information from AAERs.

    Attributes:
        nlp_engine: Spacy NLP processer for text.
        url: URL of AAER.
        text: All words in the AAER.
        bold_words: All bolded words of the AAER.
        section: The starting section (i.e. IN THE MATTER OF...) of the AAER.
        section_start: The index which the section starts in text.
        section_end: The index which the section ends in text.
        contains_21c: Whether or not the document states the company posed risk to investors.
        summary: The summary section of the AAER.
        sum_start: The index which the summary section starts in text.
        sum_end: The index which the summary section ends in text.
        company_name: The name of the company the AAER references. 
    """
    def __init__(self, url: str, nlp_engine=None):
        """Inits PDFReader with AAER document information."""
        if nlp_engine is None:
            self.nlp_engine = spacy.load("en_core_web_md")

        self.url = url
        self.text, self.bold_words = self.extract_pdf_from_url()
        self.section, self.section_start, self.section_end = self.get_section_portion()
        self.contains_21c = self.check_21c()
        self.summary, self.sum_start, self.sum_end = self.get_summary_portion()
        self.company_name = self.get_company_name()

    @staticmethod
    def find_substring(text: str, start: str, end: str) -> Tuple[int, int]:
        """Finds the start and end index of a sub-string given starting and ending sequences.

        Args:
            text: The string to find the start and end sequence in.
            start: The starting sequence.
            end: The ending sequence.

        Returns:
            The start and end index.

        Raises:
            IndexError: If either the start or end sequence can't be found.
        """
        text = text.lower()
        start_index = text.find(start.lower())
        if start_index == -1:
            raise IndexError("Start sequence: " + start + "\nCould not be found in the text")

        end_index = text[start_index:].find(end.lower())
        if end_index == -1 and end[:4] == "Resp":
            end_index = text[start_index:].find((end[:-1] + "s\n").lower())

        if end_index == -1:
            raise IndexError("End sequence: " + end + "\nCould not be found in the text after the start sequence with index " + str(start_index))

        return start_index, start_index + end_index

    def extract_pdf_from_url(self):
        """Gets text from a url of an AAER."""
        http = urllib3.PoolManager()
        temp = io.BytesIO()
        temp.write(http.request("GET", self.url).data)
        all_text = ""
        bold_words = {}
        with pdfplumber.open(temp) as pdf:
            index = start = 0
            for pdf_page in pdf.pages:
                bold_word = ""
                for char in pdf_page.chars:
                    all_text += char["text"]
                    # https://github.com/jsvine/pdfplumber
                    if "bold" in char["fontname"].lower() or len(char["text"].strip()) == 0:
                        if len(char["text"].strip()) == 0 or char["text"] in ".,1234567890'" + '"':
                            if index - start > 0 and len(bold_word) > 0:
                                # roman numeral title section
                                if bold_word in "xxiiixxivxxviiixxx":
                                    bold_word += "."

                                if bold_word not in bold_words:
                                    bold_words[bold_word] = [start]
                                else:
                                    bold_words[bold_word].append(start)
                            bold_word = ""
                            start = index + 1
                        else:
                            bold_word += char["text"].lower()
                    else:
                        start = index + 1
                    index += 1

        return all_text, bold_words

    def get_section_portion(self, start_sequence="In": str, end_sequence="I.": str) -> Tuple[str, int, int]:
        """Finds the section portion of the AAER.

        Args:
            start_sequence: The text that denotes the start of the section portion.
            end_sequence: The text that denotes the end of the section portion.

        Returns:
            Section text, along with its start and end index in the document.
        """
        # lawsuits' header section normally is bolded and begins with "In the matter of" and ends in "I. The Securities and Exch..."
        start_index = self.bold_words[start_sequence.lower()][0]
        end_index = self.bold_words[end_sequence.lower()][0] - 1

        return self.text[start_index:end_index].strip(), start_index, end_index

    def get_summary_portion(self, start_sequence="Summary": str, end_sequence="Respondent": str) -> Tuple[str, int, int]:
        """Finds the summary portion of the AAER.

        Args:
            start_sequence: The text that denotes the start of the summary portion.
            end_sequence: The text that denotes the end of the summary portion.

        Returns:
            Summary text, along with its start and end index in the document.
        """
        # the summary portion shouldn't be in the section portion
        if start_sequence.lower() in self.bold_words:
            sum_start_index = self.bold_words[start_sequence.lower()][0]
        else:
            sum_start_index = self.text.lower().find("on the basis of this order and")
        
        sum_end_index = i = 0
        if end_sequence.lower() not in self.bold_words or self.bold_words[end_sequence.lower()][-1] < sum_start_index:
            end_sequence += "s"  # sometimes the word is plural

        if end_sequence.lower() not in self.bold_words or self.bold_words[end_sequence.lower()][-1] < sum_start_index:
            sum_end_index = sum_start_index + 10000000
            for key in self.bold_words:  # find the next bolded word, which likely denotes a new section
                for index in self.bold_words[key]:
                    if sum_end_index > index > sum_start_index:
                        sum_end_index = index
        else:  # the word is bolded
            while sum_end_index < sum_start_index:
                sum_end_index = self.bold_words[end_sequence.lower()][i] - 1
                i += 1

        if sum_start_index < self.section_start:
            print("The summary was found before the starting section, please check start_sequences.")
            print("Returning the entire document.")
            return self.text[self.section_end + 1:], self.section_end + 1, -1

        return self.text[sum_start_index:sum_end_index], sum_start_index, sum_end_index

    def check_21c(self) -> bool:
        """Basic check to see if 21C exists in the section."""
        if "21c" in self.section.lower():
            return True
        return False

    def get_company_name_from_section(self) -> Optional[str]:
        """Attempts to find a company name from the section."""
        start_index, end_index = self.find_substring(self.section, "In the Matter of", "Respondent")
        title_name = self.section[start_index + 16:end_index].strip()

        comp_indicators = ["LLP", "LLC", "CORP", "INC"]
        if any(indicator in title_name.upper() for indicator in comp_indicators):
            entities = title_name.split("and")
            if len(entities) == 1:
                return title_name

            for entity in entities:
                if any(indicator in entity.upper() for indicator in comp_indicators):
                    return entity

    def get_company_name(self) -> Optional[str]:
        """Attempts to find a company name from the entire text."""
        comp_indicators = [" LTD", " LLC", " CORP", " INC", " LIMITED", " INTERNATIONAL", " CO."]
        doc = self.nlp_engine(self.text)
        company = None
        for ent in doc.ents:
            if ent.label_ == "ORG":
                if any(indicator in ent.text.upper() for indicator in comp_indicators):
                    if company is None:
                        company = ent.text.upper()
                    elif fuzz.token_set_ratio(company.split()[0], ent.text.upper().split()[0]) > .9:
                        continue
                    else:
                        return
        return company


def get_urls_from_db(rds_cursor) -> List[Tuple[str, str]]:
    """Gets unscraped AAER URLs from MySQL.

    Args:
        rds_cursor: RDS connector object.

    Returns:
        Unscraped AAER URLs and its corresponding respondents.
    """
    rds_cursor.execute(
        f"""SELECT url, respondents FROM {os.environ["TABLE"]} WHERE scraped = 0;"""
    )
    values = rds_cursor.fetchall()

    return values[::-1]


def set_scraped_db(rds_cursor, url: str) -> None:
    """Update scraped URL in MySQL."""
    rds_cursor.execute(
        f"""UPDATE {os.environ["TABLE"]} SET scraped = 1 WHERE url = '{url}';"""
    )


def add_to_dynamo(dynamodb, item: Dict) -> bool:
    """Attempts to add an item to DynamoDB.

    Args:
        item: The item to add.

    Returns:
        Whether or not the item was added successfully.
    """
    table = dynamodb.Table(os.environ["DYNAMO_TABLE"])
    response = table.put_item(Item=item)
    if "ResponseMetadata" in response and response["ResponseMetadata"]["HTTPStatusCode"] == 200:
        return True
    return False


def get_company_info(query_api, company_name: str) -> Dict:
    """Uses fuzzy string matching to find a company in the SEC API and get its info.

    Args:
        company_name: The name of the company found in the AAER.

    Returns:
        SEC query API information on the company found in the AAER. 
    """
    query = {
        "query": {
            "query_string": {
                "query": f"companyName: \"{company_name}\" AND " + \
                    "filedAt:{1990-12-31 TO 2021-12-31} AND formType:\"10-K\""
            }
        },
        "from": "0",
        "size": "1",
        "sort": [
            {
                "filedAt": {
                    "order": "desc"
                }
            }
        ]
    }

    return query_api.get_filings(query)


def scrape_pdfs(dyna_conn, rds_cursor, query_api, nlp_model=None) -> None:
    """Scrapes AAERs and adds fraudulent company information to DynamoDB.

    Args:
        dyna_conn: Connection to AWS DynamoDB object.
        rds_cursor: Connection to AWS RDS object.
        query_api: SEC query API connection object.
        nlp_model: Spacy model to process the AAER with.
    """
    if nlp_model is None:
        nlp_model = spacy.load("en_core_web_md")

    urls = get_urls_from_db(rds_cursor)
    for url, respondents in urls:
        if url[-4:] == ".pdf":
            try:
                reader = PDFReader(url)
                if reader.company_name is None:
                    print(f"Skipping {url} because a company wasn't found within {reader.section}.")
                    continue

                query = get_company_info(query_api, reader.company_name)
                if len(query["filings"]) == 0:
                    raise LookupError
                item = {
                    "cik": query["filings"][0]["cik"],
                    "company_name": query["filings"][0]["companyName"],
                    "ticker": query["filings"][0]["ticker"],
                    "url": url,
                    "itmo_section": reader.section,
                    "contains_21c": reader.contains_21c,
                }

                time_range = parse_text(reader.summary, nlp_model)  # time which the company committed fraud
                item.update(time_range)

                if add_to_dynamo(dyna_conn, item):
                    set_scraped_db(rds_cursor, url)
                print("Successfully scraped document.")
            except IndexError as e:
                print(e)
                print(f"Unable to find start/ end sequences in {url}.")
            except KeyError as e:
                print(e)
                print(f"Check {url} for bold words denoting sections.")
            except LookupError as e:
                print(e)
                print(f"{reader.company_name} doesn't exist in the SEC API.")
            time.sleep(.75)
        else:
            print(f"Skipping {url} because scraping non-pdf functionality is not supported currently.")


if __name__ == "__main__":
    # initialize resources
    dyna = boto3.resource("dynamodb")
    rds_sql_conn = pymysql.connect(
        host=os.environ["ENDPOINT"],
        user=os.environ["USER"],
        password=os.environ["PASSWORD"],
        database=os.environ["DATABASE"],
        autocommit=True,
    )
    cursor = rds_sql_conn.cursor()
    sec_query_api = QueryApi(api_key=os.environ["SEC_API_KEY"])

    scrape_pdfs(dyna, cursor, sec_query_api)
    rds_sql_conn.close()
