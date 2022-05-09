import spacy
import numpy as np

from nlp_info import misreporting_terms, month_names, quarter_to_month


def find_year(token):
    def get_year_from_child(child):
        year = None
        if child.dep_ == "pobj" or child.dep_ == "nummod":
            if child.shape_ == "dddd":
                year = int(child.text)
            elif child.shape_ == "dddd.d" or child.shape_ == "dddd.dd":
                year = int(child.text.split(".")[0])
        return year

    year = None
    for child_1 in token.children:
        for child_2 in child_1.children:
            if child_2.lemma_.lower() == "year" or child_2.lemma_.lower() in "fys":
                for child_3 in child_2.children:
                    temp = get_year_from_child(child_3)
                    if temp is not None:
                        year = temp
            else:
                temp = get_year_from_child(child_2)
                if temp is not None:
                    year = temp

    return year


def find_quarters(token):
    quantity = location = None
    for child in token.children:
        if child.dep_ == "nummod":
            quantity = child
        elif child.dep_ == "amod":
            location = child.text
    if quantity is not None:
        for child in quantity.children:
            if child.dep_ == "amod":
                location = child.text

    return location, quantity


def find_interval(years, quarters, months):
    upper = lower_in_range = 100000
    lower = upper_in_range = 0
    if len(years) > 1:
        upper = np.mean(years) + np.std(years) * 2
        lower = np.mean(years) - np.std(years) * 2
    for year in quarters:
        if year not in months:
            months[year] = []
        for quarter in quarters[year]:
            months[year].append(quarter_to_month[quarter["location"]])  # last is not necessarily 10th month, as the last 2 could mean Q3 and Q4, not just Q4, need to adjust later
    for year in months:
        for month in months[year]:
            if lower < year + month/12 < upper:
                if year + month/12 < lower_in_range:
                    lower_in_range = year + month/12
                if year + month/12 > upper_in_range:
                    upper_in_range = year + month/12

    return {
        "year_start": int(lower_in_range // 1),
        "month_start": round((lower_in_range - lower_in_range // 1) * 12),
        "year_end": int(upper_in_range // 1),
        "month_end": round((upper_in_range - upper_in_range // 1) * 12)
    }


def parse_text(text, engine):
    doc = engine(text)
    years = []
    quarters = {}
    months = {}
    for token in doc:
        # these are with higher confidence
        if token.shape_ == "dddd":
            # for year
            if (token.dep_ == "nummod" and token.head.lemma_.lower() in misreporting_terms) or \
                    token.head.text.lower() in "fys" or \
                    (token.head.shape_ == "dddd" and token.head.head.text.lower() in "fys") or \
                    token.dep_ == "pobj":
                years.append(int(token.text))
            # for month
            if token.dep_ == "nummod" and token.head.text.lower() in month_names:
                if int(token.text) in months:
                    months[int(token.text)].append(month_names[token.head.text.lower()])
                else:
                    months[int(token.text)] = [month_names[token.head.text.lower()]]
        elif token.shape_ == "dddd.d" or token.shape_ == "dddd.dd":
            # for year
            if token.dep_ == "pobj":
                years.append(int(token.text.split(".")[0]))  # in case of a citation after a punctuation
        if token.lemma_ == "quarter":
            year = find_year(token)
            if year is not None:
                loc, qty = find_quarters(token)
                if year in quarters:
                    quarters[year].append({"location": loc, "quantity": qty})
                else:
                    quarters[year] = [{"location": loc, "quantity": qty}]

    return find_interval(years, quarters, months)


if __name__ == "__main__":
    text = ""
    nlp = spacy.load("en_core_web_md")
    print(parse_text(text, nlp))
