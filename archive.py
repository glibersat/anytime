#!/bin/env python3
import csv
import locale
import logging
import os
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.DEBUG, format="%(message)s")
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)


locale.setlocale(locale.LC_TIME, "fr_FR")


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


class AnytimeCSVReader:
    """"""

    CSV_TYPES = (CSV_CB, CSV_COMPTE, CSV_UNKNOWN) = range(3)

    def __init__(self, path, target_dir):
        self.path = path
        self.target_dir = target_dir
        self.csv_type = self.CSV_UNKNOWN
        self.records = []

    def parse(self):
        with open(self.path, encoding="iso-8859-1") as csvfile:
            self._guess_type(csvfile)

            if self.csv_type == self.CSV_CB:
                LOGGER.info(bcolors.BOLD + "****** CARTE BLEUE *******" + bcolors.ENDC)
                return self.parse_cb(csvfile)
            elif self.csv_type == self.CSV_COMPTE:
                LOGGER.info(bcolors.BOLD + "****** COMPTE *******" + bcolors.ENDC)
                return self.parse_compte(csvfile)
            else:
                LOGGER.warning("Unknown CSV file, skipping")

    def parse_cb(self, csvfile):
        csvfile.seek(0)
        reader = csv.DictReader(csvfile, delimiter=";")

        self.records = []

        for row in reader:
            if row["Montant"].startswith("-"):
                sign = bcolors.FAIL + "-" + bcolors.ENDC
            else:
                sign = bcolors.OKGREEN + "+" + bcolors.ENDC

            LOGGER.info(
                f"{sign} Treating {row['Date de valeur']} --"
                f"\"{row['Description']}\" ({row['Montant']}{row['Devise']})"
            )

            self.records.append(row)

            self._check_attachments(row)

        return len(self.records)

    def parse_compte(self, csvfile):
        csvfile.seek(0)
        reader = csv.DictReader(csvfile, delimiter=";")

        self.records = []

        for row in reader:
            if row["Montant"].startswith("-"):
                sign = bcolors.FAIL + "-" + bcolors.ENDC
            else:
                sign = bcolors.OKGREEN + "+" + bcolors.ENDC

            LOGGER.info(
                f"{sign} Treating {row['Date']} --"
                f"\"{row['Description']}\" ({row['Montant']}€)"
            )
            self.records.append(row)

            self._check_attachments(row)

        return len(self.records)

    def _check_attachments(self, record):
        file_count = int(record["Documents Fournis"])

        if file_count > 0:
            LOGGER.info(
                bcolors.OKGREEN
                + f"\t`- {file_count} attachment provided"
                + bcolors.ENDC
            )
        else:
            LOGGER.warning(bcolors.WARNING + f"\t`- Missing attachment!" + bcolors.ENDC)

    def _month_from_record(self, record):
        if self.csv_type == self.CSV_CB:
            day = datetime.strptime(record["Date de valeur"], "%Y-%m-%d")
        else:
            day = datetime.strptime(record["Date"], "%Y-%m-%d %H:%M:%S")
        return day.strftime("%B")

    def download_attachments(self):
        os.makedirs(self.target_dir, exist_ok=True)

        for record in self.records:
            file_urls = record["Url"].split("\n")
            for file_url in file_urls:
                month_dir = self._month_from_record(record)
                download_dir = os.path.join(self.target_dir, month_dir)

                if self.csv_type == self.CSV_CB:
                    prefix = f"{record['Date de valeur']} - CB - "
                elif self.csv_type == self.CSV_COMPTE:
                    prefix = f"{record['Date']} - COMPTE - "

                self._download_file(file_url, download_dir, prefix=prefix)

    def copy_csv(self):
        month_dir = self._month_from_record(self.records[0])

        target_dir = os.path.join(self.target_dir, month_dir)
        os.makedirs(target_dir, exist_ok=True)

        if self.csv_type == self.CSV_CB:
            prefix = "CB"
        elif self.csv_type == self.CSV_COMPTE:
            prefix = "COMPTE"
        else:
            prefix = "INCONNU"

        shutil.copyfile(
            self.path, os.path.join(target_dir, f"{prefix}-{month_dir}.csv")
        )

    def _download_file(self, url, target_dir, prefix=None):
        os.makedirs(target_dir, exist_ok=True)

        if url.startswith("http"):
            filename = os.path.basename(url)

            if prefix:
                filename = f"{prefix}{filename}"

            target_path = os.path.join(target_dir, filename)

            if not os.path.exists(target_path):
                LOGGER.debug(
                    bcolors.OKCYAN + f"---> Retrieving {url}..." + bcolors.ENDC
                )
                urllib.request.urlretrieve(url, target_path)
            else:
                LOGGER.debug(
                    bcolors.OKCYAN
                    + f"---> {filename} already in cache, skipping"
                    + bcolors.ENDC
                )

    def _guess_type(self, csvfile):
        sniffer = csv.Sniffer()

        if not sniffer.has_header(csvfile.read(1024)):
            return self.CSV_UNKNOWN

        csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=";")
        header = next(reader)

        if len(header) == 20:
            self.csv_type = self.CSV_CB
        elif len(header) == 7:
            self.csv_type = self.CSV_COMPTE


if __name__ == "__main__":

    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} csv_dir target_dir")
        exit(1)

    target_dir = sys.argv[2]
    csv_dir = sys.argv[1]

    pathlist = Path(csv_dir).glob("**/*.csv")
    for path in pathlist:
        LOGGER.info(f"Found CSV file {path}")
        csv_reader = AnytimeCSVReader(str(path), target_dir)
        if csv_reader.parse():
            csv_reader.copy_csv()
            csv_reader.download_attachments()
        else:
            LOGGER.warning("No record found in CSV, skipping!")

    # make zip
    shutil.make_archive(target_dir, "zip", target_dir)

    exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} csv_cpt csv_cb target_dir")
        exit(1)

    os.makedirs(os.path.join(sys.argv[3], FILE_DIR), exist_ok=True)

    shutil.copyfile(sys.argv[1], os.path.join(sys.argv[3], sys.argv[1]))
    with open(sys.argv[1], encoding="iso-8859-1") as csvfile:
        reader = csv.reader(csvfile, delimiter=";")
        print(bcolors.BOLD + "****** BANK ACCOUNT *******" + bcolors.ENDC)
        treat_cpt(reader, sys.argv[3])

    shutil.copyfile(sys.argv[2], os.path.join(sys.argv[3], sys.argv[2]))
    with open(sys.argv[2], encoding="iso-8859-1") as csvfile:
        reader = csv.reader(csvfile, delimiter=";")
        print(bcolors.BOLD + "****** CARD ACCOUNT *******" + bcolors.ENDC)
        treat_cb(reader, sys.argv[3])

    # make zip
    shutil.make_archive(f"{sys.argv[3]}", "zip", sys.argv[3])
