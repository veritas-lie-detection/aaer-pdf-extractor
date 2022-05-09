FROM ubuntu:20.04

WORKDIR /usr/src/pdf-scraper
COPY . .
RUN apt-get update && apt-get install -y python3-pip
RUN pip3 install --no-cache-dir -r requirements.txt \
    && python3 -m spacy download en_core_web_md

CMD ["python3", "src/pdf_miner.py"]