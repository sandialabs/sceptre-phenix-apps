"""
this file is run on a separate pid so that the component can run in
the background without holding up other scorch components
(scorch doesn't allow threads to run detached).
"""

import csv
import json
import re
import sys
import time

from kafka import KafkaConsumer


def run(csvBool, path, kafka_ips, topics, exp_name, wait_duration_seconds):
    kafka_ips = kafka_ips.split(",")
    topics = json.loads(topics)

    # kafka consumer
    consumer = KafkaConsumer(
        # bootstrap ip and port could probably be separate variables
        bootstrap_servers=kafka_ips,
        auto_offset_reset="latest",
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )

    # get all topic names
    if not topics:
        consumer.subscribe(pattern=(exp_name + ".*"))
    else:
        start = time.time()

        # list of all topic names we want the consumer to subscribe to
        subscribedTopics = []
        foundTopics = False

        for topic in topics:
            name = topic.get("name")

            # handle wildcards in the name, this only supports right
            # wildcards
            if "*" in name:
                foundTopics = False
                filteredName = name.split("*", 1)[0]

                # we don't care about anything right of the wildcard
                pattern = f"^{re.escape(filteredName)}.*"

                # if this is a new experiment, kafka may not have populated
                # any tags... so wait until it has (up to 305 seconds,
                # then quit)
                while not foundTopics and (time.time() - start) < int(
                    wait_duration_seconds
                ):
                    for topic in consumer.topics():
                        if (
                            str(filteredName) in str(topic)
                            and topic not in subscribedTopics
                        ):
                            subscribedTopics.append(topic)
                    if subscribedTopics:
                        foundTopics = True
            elif name and name not in subscribedTopics:
                subscribedTopics.append(name)

        # subscribe to all topic names
        consumer.subscribe(subscribedTopics)

    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = None
        wrote_header = False
        all_keys = set()

        while True:
            for message in consumer:
                storeMessage = False

                # grab unfiltered/ unprocessed message data
                data = message.value

                if not topics:
                    if csvBool:
                        all_keys.update(data.keys())

                        if writer is None:
                            writer = csv.DictWriter(
                                file,
                                fieldnames=["topic", *sorted(all_keys)],
                                extrasaction="ignore",
                            )

                            # check if the first line in the csv has
                            # been written yet, write it if not
                            if not wrote_header:
                                writer.writeheader()
                                wrote_header = True
                    # store topic
                    topicVal = message.topic

                    storeMessage = True

                # for each topic, check if this message has the
                # desired key and value
                for topic in topics:
                    # if null filter
                    if not topic.get("filter", []):
                        if csvBool:
                            all_keys.update(data.keys())

                            if writer is None:
                                writer = csv.DictWriter(
                                    file,
                                    fieldnames=["topic", *sorted(all_keys)],
                                    extrasaction="ignore",
                                )

                                # check if the first line in the csv has
                                # been written yet, write it if not
                                if not wrote_header:
                                    writer.writeheader()
                                    wrote_header = True
                        # store topic
                        topicVal = message.topic

                        storeMessage = True
                        continue

                    for filterVal in topic.get("filter", []):
                        key = filterVal.get("key")
                        value = filterVal.get("value")

                        if key in data:
                            actualValue = str(data.get(key)).lower()
                            pattern = str(value).lower()

                            # use regular expressions to account for wildcards
                            pattern = re.escape(pattern).replace(r"\*", ".*")

                            regex = re.compile(f"^{pattern}$", re.IGNORECASE)
                            if regex.match(actualValue):
                                if csvBool:
                                    all_keys.update(data.keys())

                                    if writer is None:
                                        writer = csv.DictWriter(
                                            file,
                                            fieldnames=["topic", *sorted(all_keys)],
                                            extrasaction="ignore",
                                        )

                                        # check if the first line in the csv has
                                        # been written yet, write it if not
                                        if not wrote_header:
                                            writer.writeheader()
                                            wrote_header = True
                                # store topic
                                topicVal = message.topic

                                storeMessage = True

                if storeMessage:
                    # output topic name
                    row = {"topic": topicVal}
                    row.update(data)

                    # write the data and flush the data to ensure that we
                    # don't save to buffer
                    if csvBool:
                        writer.writerow(row)
                    else:
                        file.write(json.dumps(row) + "\n")
                    file.flush()


def main():
    run()


if __name__ == "__main__":
    # unpack the args
    csvBool = sys.argv[1].lower() == "true"
    path = sys.argv[2]
    kafka_ips = sys.argv[3]
    topics = sys.argv[4]
    exp_name = sys.argv[5]
    wait_duration_seconds = sys.argv[6]

    run(csvBool, path, kafka_ips, topics, exp_name, wait_duration_seconds)
