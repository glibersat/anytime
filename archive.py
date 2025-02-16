#!/bin/env python3
import magic
import csv
import locale
import logging
import os
import shutil
import sys
import requests
from datetime import datetime
from pathlib import Path
import time

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import print
from rich.layout import Layout
from rich.logging import RichHandler


from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

logging.basicConfig(level="NOTSET", format="%(message)s", handlers=[RichHandler()])
LOGGER = logging.getLogger(__name__)

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
                f'"{row["Description"]}" ({row["Montant"]}{row["Devise"]})'
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
                f'"{row["Description"]}" ({row["Montant"]}€)'
            )
            self.records.append(row)

            self._check_attachments(row)

        return len(self.records)

    def attachment_count(self, record):
        file_count = int(record["Documents Fournis"])
        return file_count

    def _check_attachments(self, record):
        file_count = self.attachment_count(record)

        if file_count:
            LOGGER.info(
                bcolors.OKGREEN
                + f"\t`- {file_count} attachment provided"
                + bcolors.ENDC
            )
        else:
            LOGGER.warning(bcolors.WARNING + "\t`- Missing attachment!" + bcolors.ENDC)

    def date_from_record(self, record):
        if self.csv_type == self.CSV_CB:
            day = datetime.strptime(record["Date de valeur"], "%Y-%m-%d")
        else:
            day = datetime.strptime(record["Date"], "%Y-%m-%d %H:%M:%S")

        return day

    def _month_from_record(self, record):
        day = self.date_from_record(record)
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

                if file_path := self._download_file(
                    file_url, download_dir, prefix=prefix
                ):
                    record["PJ"] = file_path

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

            cache_path = os.path.join(target_dir, f"{filename}.data")

            if not os.path.exists(cache_path):
                LOGGER.debug(
                    bcolors.OKCYAN + f"---> Retrieving {url}..." + bcolors.ENDC
                )
                r = requests.get(url, stream=True)
                if r.ok:
                    # First, copy as raw since we don't know the filetype
                    with open(cache_path, "wb") as f:
                        r.raw.decode_content = True
                        shutil.copyfileobj(r.raw, f)
                else:
                    LOGGER.warning(f"Unable to download {url}")
                    return None
            else:
                LOGGER.debug(
                    bcolors.OKCYAN
                    + f"---> {filename} already downloaded, skipping"
                    + bcolors.ENDC
                )

            # Now we have the data, try to guess what type we have
            # using mimetype
            mime = magic.from_file(cache_path)
            mime = mime.lower()
            extension = "??"
            if ("jpg" in mime) or ("jpeg" in mime):
                extension = "jpg"
            elif "png" in mime:
                extension = "png"
            elif "pdf" in mime:
                extension = "pdf"

            shutil.copy(cache_path, os.path.join(target_dir, f"{filename}.{extension}"))
            target_path = cache_path

            return target_path

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


class Header:
    """Display header with clock."""

    def __rich__(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            "[b]Anytime[/b] CSV checker/extractor",
        )
        return Panel(grid, style="white on blue")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} csv_dir target_dir")
        exit(1)

    target_dir = sys.argv[2]
    csv_dir = sys.argv[1]

    overall_progress = Progress()

    layout = Layout(name="Root")
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=8),
    )

    layout["header"].update(Header())

    table = Table(title="Operations")
    table.add_column("Date", justify="right", style="cyan", no_wrap=True)
    table.add_column("Compte", justify="left", style="magenta", no_wrap=True)
    table.add_column("Description", justify="right", style="cyan", no_wrap=True)
    table.add_column("Montant", style="green")
    table.add_column("Justificatif?", justify="middle", style="green")

    layout["main"].update(Panel(table))

    pathlist = sorted(Path(csv_dir).glob("**/*.csv"))

    console = Console()

    progress = Progress(
        "{task.description}",
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    )
    for path in pathlist:
        progress.add_task(path)

    layout["footer"].update(Panel(progress, title="Progression", border_style="green"))

    missing_attachments = []

    with Live(layout, refresh_per_second=10, screen=True):
        for idx, path in enumerate(pathlist):
            LOGGER.info(f"Found CSV file {path}")
            csv_reader = AnytimeCSVReader(str(path), target_dir)
            if csv_reader.parse():
                csv_type = {
                    AnytimeCSVReader.CSV_CB: "CB",
                    AnytimeCSVReader.CSV_COMPTE: "Compte Courant",
                }[csv_reader.csv_type]

                # Add generated records to table
                for record_idx, record in enumerate(csv_reader.records):
                    time.sleep(0.01)
                    attach_count = csv_reader.attachment_count(record)
                    table.add_row(
                        csv_reader.date_from_record(record).strftime("%Y-%m-%d"),
                        str(csv_type),
                        f"{record['Description']}",
                        f"{record['Montant']}€",
                        str(attach_count),
                    )

                    progress.update(
                        idx, completed=record_idx / len(csv_reader.records) * 80
                    )

                    if attach_count == 0:
                        missing_attachments.append(
                            (
                                csv_reader.date_from_record(record).strftime(
                                    "%Y-%m-%d"
                                ),
                                str(csv_type),
                                f"{record['Description']}",
                                f"{record['Montant']}€",
                            )
                        )

                csv_reader.copy_csv()
                progress.update(idx, completed=90)
                csv_reader.download_attachments()
                progress.update(idx, completed=100)
            else:
                LOGGER.warning("No record found in CSV, skipping!")

    # make zip
    LOGGER.info("Making ZIP archive for your accountant!")
    shutil.make_archive(target_dir, "zip", target_dir)

    LOGGER.info("Writing missing attachment file to justificatifs-manquants.csv")
    with open(f"{target_dir}/justificatifs-manquants.csv", "w") as csvfile:
        csvwriter = csv.writer(csvfile)
        for attachment in missing_attachments:
            csvwriter.writerow(attachment)

    exit(0)
