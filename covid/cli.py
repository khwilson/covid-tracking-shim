"""
CLI for accessing various parts of the Covid data ecosystem
"""
import codecs
import csv
import gzip
import io
import sys
from contextlib import contextmanager
from typing import ContextManager, Iterable, Optional

import click
import requests


@contextmanager
def _open_for_write(output: Optional[str]) -> ContextManager[io.TextIOBase]:
    output = output or "-"
    if output == "-":
        yield sys.stdout
    else:
        if output.endswith(".gz"):
            with gzip.open(output, "wt") as outfile:
                yield outfile
        else:
            with open(output, "wt") as outfile:
                yield outfile


def iterable_to_stream(
    iterable: Iterable[bytes], buffer_size: int = io.DEFAULT_BUFFER_SIZE
) -> io.BufferedReader:
    """
    Lets you use an iterable (e.g. a generator) that yields bytestrings as a read-only
    input stream.

    The stream implements Python 3's newer I/O API (available in Python 2's io module).
    For efficiency, the stream is buffered.

    Ganked from:
        https://stackoverflow.com/questions/59162868/python-requests-stream-iter-content-chunks-into-a-pandas-read-csv-function
    """

    class IterStream(io.RawIOBase):
        def __init__(self):
            self.leftover = None

        def readable(self):
            return True

        def readinto(self, b):
            try:
                l = len(b)  # We're supposed to return at most this much
                chunk = self.leftover or next(iterable)
                output, self.leftover = chunk[:l], chunk[l:]
                b[: len(output)] = output
                return len(output)
            except StopIteration:
                return 0  # indicate EOF

    return io.BufferedReader(IterStream(), buffer_size=buffer_size)


@click.group()
def cli():
    """ Functions for interacting with Covid data sources """
    pass


@cli.group("cdc")
def cdc_group():
    """ Functions for interacting with CDC data streams """


@cdc_group.command("cases")
@click.option(
    "--limit",
    "-l",
    default=500,
    type=int,
    help="The page size for paging through CDC data",
)
@click.option(
    "--max-records",
    "-m",
    default=None,
    type=int,
    help="The (soft) maximum number of records to download",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(allow_dash=True),
    default=None,
    help="The location to write the data out to. Default is stdout",
)
def cdc_cases_command(limit: int, max_records: Optional[int], output: Optional[str]):
    url_format = f"https://data.cdc.gov/resource/9mfq-cb36.csv?$limit={limit}&$offset={{offset}}&$order=:id"

    session = requests.session()
    current_offset = 0
    headers = None
    with _open_for_write(output) as outfile:
        writer = csv.writer(outfile)

        while True:
            if max_records and current_offset >= max_records:
                break

            with session.get(
                url_format.format(offset=current_offset), stream=True
            ) as response:
                response.raise_for_status()
                reader = csv.reader(
                    io.TextIOWrapper(
                        iterable_to_stream(response.iter_content(chunk_size=8192))
                    )
                )

                # This might be a little ridiculous but technically nothing is stopping them from
                # reordering the column order in the CSV between pulls.
                these_headers = next(reader)
                if not headers:
                    headers = these_headers
                    sort_order = list(range(len(headers)))
                    writer.writerow(headers)
                else:
                    sort_order = [these_headers.index(header) for header in headers]

                written_any = False
                for line in reader:
                    written_any = True
                    writer.writerow([line[i] for i in sort_order])

                if not written_any:
                    break

            current_offset += limit
