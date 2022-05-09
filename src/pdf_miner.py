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

from nlp_engine import parse_text


class PDFReader:
    def __init__(self, url: str, nlp_engine=None):
        if nlp_engine is None:
            self.nlp_engine = spacy.load("en_core_web_md")

        self.url = url
        self.text, self.bold_words = self.extract_pdf_from_url()
        self.section, self.section_start, self.section_end = self.get_section_portion()
        self.contains_21c = self.check_21c()
        self.summary, self.sum_start, self.sum_end = self.get_summary_portion()
        self.company_name = self.get_company_name()

    @staticmethod
    def find_substring(text, start, end):
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

    def get_section_portion(self, start_sequence="In", end_sequence="I."):
        # lawsuits' header section normally begins with "In the matter of" and ends in "I. The Securities and Exch..."
        start_index = self.bold_words[start_sequence.lower()][0]
        end_index = self.bold_words[end_sequence.lower()][0] - 1

        return self.text[start_index:end_index].strip(), start_index, end_index

    def get_summary_portion(self, start_sequence="Summary", end_sequence="Respondent"):  # summary is always (?) section 3
        # the summary portion shouldn't be in the section portion
        if start_sequence.lower() in self.bold_words:
            sum_start_index = self.bold_words[start_sequence.lower()][0]
        else:
            sum_start_index = self.text.lower().find("on the basis of this order and")
        
        sum_end_index = i = 0
        if end_sequence.lower() not in self.bold_words or self.bold_words[end_sequence.lower()][-1] < sum_start_index:
            end_sequence += "s"
        if end_sequence.lower() not in self.bold_words or self.bold_words[end_sequence.lower()][-1] < sum_start_index:
            sum_end_index = sum_start_index + 10000000
            for key in self.bold_words:
                for index in self.bold_words[key]:
                    if sum_end_index > index > sum_start_index:
                        sum_end_index = index
        else:
            while sum_end_index < sum_start_index:
                sum_end_index = self.bold_words[end_sequence.lower()][i] - 1
                i += 1

        if sum_start_index < self.section_start:
            print("The summary was found before the starting section, please check start_sequences.")
            print("Returning the entire document.")
            return self.text[self.section_end + 1:], self.section_end + 1, -1

        return self.text[sum_start_index:sum_end_index], sum_start_index, sum_end_index

    def check_21c(self):
        if "21c" in self.section.lower():
            return True
        return False

    def get_company_name_from_section(self):
        index = self.find_substring(self.section, "In the Matter of", "Respondent")
        title_name = self.section[index[0]+16:index[1]].strip()
        comp_indicators = ["LLP", "LLC", "CORP", "INC"]
        if any(x in title_name.upper() for x in comp_indicators):
            temp = title_name.split("and")
            if len(temp) == 1:
                return title_name
            for i in temp:
                if any(x in i.upper() for x in comp_indicators):
                    return i

    def get_company_name(self):
        comp_indicators = [" LTD", " LLC", " CORP", " INC", " LIMITED", " INTERNATIONAL", " CO."]
        doc = self.nlp_engine(self.text)
        company = None
        for ent in doc.ents:
            if ent.label_ == "ORG":
                if any(x in ent.text.upper() for x in comp_indicators):
                    if company is None:
                        company = ent.text.upper()
                    elif fuzz.token_set_ratio(company.split()[0], ent.text.upper().split()[0]) > .9:
                        continue
                    else:
                        return
        return company


def get_urls_from_db(rds_cursor):
    rds_cursor.execute(
        f"""SELECT url, respondents FROM {os.environ["TABLE"]} WHERE scraped = 0;"""
    )
    values = rds_cursor.fetchall()

    return values[::-1]


def set_scraped_db(rds_cursor, url):
    rds_cursor.execute(
        f"""UPDATE {os.environ["TABLE"]} SET scraped = 1 WHERE url = '{url}';"""
    )


def add_to_dynamo(dynamodb, item):
    table = dynamodb.Table(os.environ["DYNAMO_TABLE"])
    response = table.put_item(Item=item)
    if "ResponseMetadata" in response and response["ResponseMetadata"]["HTTPStatusCode"] == 200:
        return True
    return False


def get_company_info(query_api, company_name):
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


def scrape_pdfs(dyna_conn, rds_cursor, query_api, nlp_model=None):
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

                time_range = parse_text(reader.summary, nlp_model)
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
