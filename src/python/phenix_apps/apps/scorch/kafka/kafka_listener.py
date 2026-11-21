"""
this file is run on a separate pid so that the component can run in
the background without holding up other scorch components
(scorch doesn't allow threads to run detached).

Its own stdout and stderr go to <name>_listener.log beside its output.
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

from kafka import KafkaConsumer

# a row is written whatever its size, so reading it back (to widen the header)
# must accept any size too; the default limit is 131072 characters
csv.field_size_limit(sys.maxsize)


def topic_matches(name, topic):
    """A topic name matches exactly, or by its prefix when it ends in a
    wildcard (only right wildcards are supported)."""
    if "*" in name:
        return topic.startswith(name.split("*", 1)[0])
    return topic == name


def decode(raw):
    """A message's JSON object, or None (logged) when it is not one: a bad
    message is skipped, it does not end the listener."""
    if raw is None:  # a tombstone (a record with no value)
        print("kafka listener: skipping a message with no value", file=sys.stderr)
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as ex:
        print(
            f"kafka listener: skipping a message that is not JSON: {ex}",
            file=sys.stderr,
        )
        return None
    if not isinstance(data, dict):
        print(
            f"kafka listener: skipping a message that is not a JSON object: "
            f"{type(data).__name__}",
            file=sys.stderr,
        )
        return None
    return data


def _value_matches(want, actual):
    # case-insensitive, with * as a wildcard
    pattern = re.escape(str(want).lower()).replace(r"\*", ".*")
    return re.fullmatch(pattern, str(actual).lower(), re.IGNORECASE) is not None


def keep(topics, topic, data):
    """Whether to store a message: with no topics, every message; otherwise a
    topic entry matching this message's topic whose filters are empty or of
    which one matches (filters are alternatives)."""
    if not topics:
        return True
    for entry in topics:
        if not topic_matches(entry.get("name", ""), topic):
            continue
        filters = entry.get("filter") or []
        if not filters or any(
            f.get("key") in data and _value_matches(f.get("value"), data[f.get("key")])
            for f in filters
        ):
            return True
    return False


class CsvSink:
    """Appends rows to a CSV whose header is every key seen so far. A row with
    a new key rewrites the file under the wider header, so no column is lost
    and every row lines up under one header."""

    def __init__(self, path):
        self.path = Path(path)
        self.fields = []
        if self.path.exists() and self.path.stat().st_size:
            with self.path.open(newline="", encoding="utf-8") as f:
                self.fields = next(csv.reader(f), [])
        self.file = None

    def write(self, row):
        new = set(row) - set(self.fields)
        if new or self.file is None:
            if new:
                keys = (set(self.fields) | set(row)) - {"topic"}
                self._widen(["topic", *sorted(keys)])
            self.file = self.path.open("a", newline="", encoding="utf-8")
            self.writer = csv.DictWriter(self.file, self.fields, restval="")
            if not self.path.stat().st_size:
                self.writer.writeheader()
        self.writer.writerow(row)
        self.file.flush()

    def _widen(self, fields):
        if self.file is not None:
            self.file.close()
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fields, restval="")
            writer.writeheader()
            if self.path.exists():
                # row by row: the output can be large
                with self.path.open(newline="", encoding="utf-8") as f:
                    writer.writerows(csv.DictReader(f))
        os.replace(tmp, self.path)
        self.fields = fields


class JsonSink:
    """Appends each row as one line of JSON."""

    def __init__(self, path):
        self.file = Path(path).open("a", encoding="utf-8")

    def write(self, row):
        self.file.write(json.dumps(row) + "\n")
        self.file.flush()


def subscribe(consumer, topics, exp_name, wait_duration_seconds):
    if not topics:
        consumer.subscribe(pattern=(exp_name + ".*"))
        return

    start = time.time()

    # list of all topic names we want the consumer to subscribe to
    subscribed = []
    for topic in topics:
        name = topic.get("name")
        if "*" in name:
            # if this is a new experiment, kafka may not have populated
            # any topics... so wait until it has (up to
            # wait_duration_seconds, then go on without them)
            found = False
            while True:
                for t in sorted(consumer.topics()):
                    if topic_matches(name, t):
                        found = True
                        if t not in subscribed:
                            subscribed.append(t)
                if found or time.time() - start >= int(wait_duration_seconds):
                    break
                time.sleep(1)
        elif name and name not in subscribed:
            subscribed.append(name)

    consumer.subscribe(subscribed)


def run(csvBool, path, kafka_ips, topics, exp_name, wait_duration_seconds):
    topics = json.loads(topics)

    consumer = KafkaConsumer(
        bootstrap_servers=kafka_ips.split(","),
        auto_offset_reset="latest",
        enable_auto_commit=False,
        value_deserializer=decode,
    )
    subscribe(consumer, topics, exp_name, wait_duration_seconds)

    sink = CsvSink(path) if csvBool else JsonSink(path)
    while True:
        for message in consumer:
            data = message.value
            if data is not None and keep(topics, message.topic, data):
                sink.write({"topic": message.topic, **data})


if __name__ == "__main__":
    # unpack the args; a trailing component id is ignored (cleanup matches it)
    run(
        sys.argv[1].lower() == "true",
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
        sys.argv[5],
        sys.argv[6],
    )
