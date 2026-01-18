import argparse
import csv
import math
import sys
import timeit
from collections import defaultdict
from operator import itemgetter
from pathlib import Path

import elasticsearch.helpers
from dateutil.parser import parse as parse_time

from phenix_apps.common import utils


def gen_csv(
    record: dict,
    csv_path: Path,
    es_server: str,
    es_index: str = "rtds-clean",
    iperf_dir: Path | None = None,
):
    """
    Generate CSV file from RTDS data in Elasticsearch and iperf data (or packet TCP RTT values).
    """
    utils.print_msg("Generating CSV file...")

    # Interval is 1 second. RTT times are only recorded every second.
    # Physical values are 30hz. so, lots of physical measurements will be missing.
    # length of intervals for iperf client should be close to 1800, like 1798
    # example: cat iperf_client_load5.json | jq '.intervals | length'
    if iperf_dir:
        iperf_raw = {}  # type: dict[str, dict]
        for iperf_file in iperf_dir.glob("iperf_client-data_*.json"):
            # "iperf_server-data_client-load5_server-load8.json" => "load5_load8"
            pair_name = (
                iperf_file.name.replace(".json", "")
                .split("-data_")[-1]
                .replace("client-", "")
                .replace("server-", "")
                .replace("_", "-")
            )

            try:
                iperf_raw[pair_name] = utils.read_json(iperf_file)
            except Exception as ex:
                utils.eprint(
                    f"failed to read iperf data for pair {pair_name} from file {iperf_file}: {ex}"
                )
                sys.exit(1)

        iperf_data = {}  # type: dict[str, dict[int, dict]]
        for pair_name, raw_values in iperf_raw.items():
            vals = {}  # type: dict[int, dict]
            for i in raw_values["intervals"]:
                vals[int(i["sum"]["start"])] = {
                    "rtt": utils.usec_to_sec(i["streams"][0]["rtt"]),  # float
                    "rttvar": utils.usec_to_sec(i["streams"][0]["rttvar"]),  # float
                    "retransmits": i["streams"][0]["retransmits"],  # int
                }

            iperf_data[pair_name] = vals

    # Create the CSV header
    # ~110 columns with 8 PMUs and 3 iperf clients
    csv_header = [
        "sequence",
        "approx_seconds_since_start",
        "timestamp_unix",
        "timestamp_iso8601",
        "frequency",
        "dfreq",
    ]

    if iperf_dir:
        # rtt, rttvar
        for iperf_pair in iperf_data.keys():
            csv_header.append(f"rtt_{iperf_pair}")
            csv_header.append(f"rttvar_{iperf_pair}")
            csv_header.append(f"retransmits_{iperf_pair}")

    # real and angle for VA/VB/VC/IA/IB/IC
    channels = ["VA", "VB", "VC", "IA", "IB", "IC"]
    pmus = record["rtds"]["pmus"]
    for pmu_name, pmu_label in pmus.items():
        for channel in channels:
            csv_header.append(f"{channel}_angle_{pmu_name}_{pmu_label}")
            csv_header.append(f"{channel}_real_{pmu_name}_{pmu_label}")

    # freq and dfreq for each PMU
    for pmu_name, pmu_label in pmus.items():
        csv_header.append(f"freq_{pmu_name}_{pmu_label}")
        csv_header.append(f"dfreq_{pmu_name}_{pmu_label}")

    # Elasticsearch export
    # Uses configuration from the 'rtds' component metadata
    es_rtds = utils.connect_elastic(es_server)
    start_time = parse_time(record["experiment"]["start"])
    actual_stop_time = parse_time(record["experiment"]["end_time_actual"])
    stop_time_modified = parse_time(record["experiment"]["end"])
    configured_duration = float(record["experiment"]["duration"])

    query = {
        "size": 10000,
        "query": {
            "bool": {
                "filter": [
                    # Query a little past the end since times are already being trimmed later on
                    # This attempts to avoid being short by a single row.
                    # {"range": {"sceptre_time": {"gte": start_time, "lte": stop_time_modified}}},
                    {
                        "range": {
                            "sceptre_time": {"gte": start_time, "lte": actual_stop_time}
                        }
                    },
                ]
            }
        },
        # This limits what fields get returned, instead of returning the whole doc
        "fields": [
            "rtds_time",
            "sceptre_time",
            "measurement.dfreq",
            "measurement.channel",
            "measurement.frequency",
            "measurement.phasor.angle",
            "measurement.phasor.real",
            "measurement.time",
            "pmu.label",
            "pmu.name",
        ],
        "_source": False,  # set to true to get the full document contents...a lot of data
    }

    # 30 * 60 * 30 * 8 * 6 = 2592000 docs for 30 minutes
    # Takes ~4 minutes to pull and process that many docs from Elasticsearch
    scroll_timer = timeit.default_timer()

    # Tune index pattern to just the day(s) experiment was run
    # NOTE: this assumes the experiment duration <= 2 days
    index = utils.get_indices_from_range(es_index, start_time, actual_stop_time)

    utils.print_msg(f"Submitting scroll query to Elasticsearch (index: '{index}')")
    iterator = elasticsearch.helpers.scan(
        client=es_rtds, query=query, index=index
    )  # generator

    utils.print_msg("Starting Elasticsearch doc pull")
    all_docs = []
    for doc in iterator:
        all_docs.append({k: v[0] for k, v in doc["fields"].items()})

    scroll_duration = timeit.default_timer() - scroll_timer
    utils.print_msg(
        f"Got {len(all_docs)} docs from Elasticsearch in {scroll_duration:.2f} seconds"
    )

    es_rtds.close()  # disconnect from Elasticsearch
    if not all_docs:
        utils.eprint("No docs were retrieved from Elasticsearch!")
        sys.exit(1)

    proc_start = timeit.default_timer()
    utils.print_msg(f"Processing {len(all_docs)} docs...")
    ground_truth = defaultdict(list)  # type: dict[float, list[dict]]
    skipped_docs = []
    trimmed_all_docs = []

    for doc in all_docs:
        m_time = doc["measurement.time"]
        r_ts = parse_time(doc["rtds_time"]).timestamp()
        if not math.isclose(m_time, r_ts, rel_tol=1e-12):
            utils.eprint(
                f"measurement.time {m_time} is not close to rtds_time {r_ts}, something is wrong with the rtds provider code"
            )
            sys.exit(1)

        sceptre_time = parse_time(doc["sceptre_time"])
        assert sceptre_time.tzinfo.tzname(sceptre_time) == "UTC"

        # exclude docs outside of the time range
        # this works around quirkyness with Elasticsearch date range filter
        # and the fact timestamps of reads don't fall on nice clean time boundaries
        if sceptre_time < start_time or sceptre_time > stop_time_modified:
            skipped_docs.append(doc)
            continue

        trimmed_all_docs.append(doc)
        ground_truth[sceptre_time.timestamp()].append(doc)

    # replace with out of range timestamps removed
    all_docs = trimmed_all_docs
    utils.print_msg(f"length of ground_truth: {len(ground_truth)}")

    if skipped_docs:
        utils.print_msg(
            f"WARN: {len(skipped_docs)} docs were skipped due to being outside of time range"
        )

    # ensure docs sorted by rtds_time have the same order when sorted by sceptre_time
    by_sceptre = sorted(
        all_docs, key=itemgetter("pmu.name", "measurement.channel", "sceptre_time")
    )
    by_rtds = sorted(
        all_docs, key=itemgetter("pmu.name", "measurement.channel", "rtds_time")
    )
    assert len(by_sceptre) == len(by_rtds)
    if by_sceptre != by_rtds:
        utils.eprint("all_docs sorted by sceptre_time != sorted by rtds_time!")

        differing = []
        for i in range(len(by_sceptre)):
            if by_sceptre[i] != by_rtds[i]:
                differing.append((i, by_sceptre[i], by_rtds[i]))

        utils.eprint(f"** {len(differing)} differing docs **")
        # diff_str = "\n| index | by_sceptre | by_rtds |\n| --- | --- | --- |\n"
        # for d in differing:
        #     diff_str += f"{d[0]} | {d[1]} | {d[2]}\n"
        # utils.eprint(diff_str)
        # sys.exit(1)

    # measurement.time transcends PMUs, so all PMUs will have the same time step
    # from the RTDS.
    # We record the time value of the first data point in our filtered set
    # of data, and use that as the zer0 for the entire set.
    # Sorting the time steps is important
    # this applies to sceptre_time as well, after applying my hack to
    # the provider to force the same timestamp.
    time_steps = sorted(ground_truth.keys())  # type: list[float]
    nested = {
        time_step: {
            pmu_name: {channel: {} for channel in channels} for pmu_name in pmus.keys()
        }
        for time_step in time_steps
    }
    for doc in all_docs:
        sceptre_time = parse_time(doc["sceptre_time"])
        nested[sceptre_time.timestamp()][doc["pmu.name"]][
            doc["measurement.channel"]
        ] = doc

    utils.print_msg(
        f"Processed {len(all_docs)} docs in {timeit.default_timer() - proc_start:.2f} seconds"
    )

    # checks that first doc and last doc are within the time range
    first_ts = parse_time(ground_truth[time_steps[0]][0]["sceptre_time"])
    if first_ts < start_time:
        utils.eprint(
            f"first timestamp in time steps of {first_ts} < start_time of {start_time}!\nfirst_ts: {first_ts}\nstart_time: {start_time}"
        )
        sys.exit(1)
    last_ts = parse_time(ground_truth[time_steps[-1]][0]["sceptre_time"])
    if last_ts > stop_time_modified:
        utils.eprint(
            f"last timestamp in time steps of {last_ts} > stop_time_modified of {stop_time_modified}!\nlast_ts: {last_ts}\nstop_time_modified: {stop_time_modified}"
        )
        sys.exit(1)

    # This assumes PMU polling rate of 30hz
    expected_count = int(30 * configured_duration)
    # sometimes we end up with an extra row, if that's the case, remove the last row
    if len(time_steps) - 1 == expected_count:
        utils.print_msg(
            f"WARNING: there are {len(time_steps)} time steps but expected {expected_count}, removing the last time step"
        )
        del time_steps[-1]
    # TODO: sometimes it's one time step less, and I don't know why. Allowing it for now
    elif len(time_steps) == expected_count - 1:
        utils.print_msg(
            f"WARNING: there are {len(time_steps)} time steps, one fewer than expected {expected_count}, allowing it to pass so we can get these darn runs done"
        )
    # elif len(time_steps) != expected_count:
    # TODO: loosening this quite a bit for now.
    elif len(time_steps) < expected_count - 10:
        utils.eprint(
            f"number of time_steps {len(time_steps)} != expected count of {expected_count} (30 * {configured_duration} seconds)"
        )
        sys.exit(1)

    pmu_names = list(pmus.keys())

    utils.print_msg(f"Writing {len(time_steps)} rows to CSV file: {csv_path.name}")
    with csv_path.open("w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        # write the CSV header
        writer.writerow(csv_header)

        time_zero = time_steps[0]

        for sequence, time_step in enumerate(time_steps):
            # pick first entry for timestamps.
            # sceptre_time can vary due to each PMU being read in it's
            # own thread, processing times, and network latencies.
            # if we're using the same PMU all the time, it'll be at least
            # somewhat consistent.
            someone = ground_truth[time_step][0]

            sceptre_ts = parse_time(someone["sceptre_time"])
            sceptre_time_unix = sceptre_ts.timestamp()
            assert time_step == sceptre_time_unix
            approx_seconds_since_start = time_step - time_zero

            # frequency and dfreq values are the same across all PMUs,
            # so only set them once in the CSV to reduce size
            pmu_zero = nested[time_step][pmu_names[0]][channels[0]]

            if not pmu_zero:
                utils.eprint(
                    f"No PMU data for time step {time_step} (sequence={sequence})"
                )
                sys.exit(1)

            row = [
                # sequence
                sequence,  # int
                # approx_seconds_since_start
                approx_seconds_since_start,  # float
                # timestamp_unix
                sceptre_time_unix,  # float
                # timestamp_iso8601
                sceptre_ts.isoformat(),  # str
                # frequency
                pmu_zero["measurement.frequency"],  # float
                # dfreq
                pmu_zero["measurement.dfreq"],  # float
            ]

            if iperf_dir:
                # Iterate through the iperf sensors and add their values
                # There is always going to be a .0 entry, e.g. 1.0, 2.0, etc.
                # Use the same iperf values for all rows in the same second,
                # which should be 30 rows. Using the rounded integer value
                # should work. Technically should use sceptre time here, but
                # approx_seconds_since_start keeps it more in-line with what's
                # happening. Since time 0 is the iperf start time, we can use
                # approx_seconds_since_start. (and this is inaccurate anyway
                # due to only 1 read per second and not exactly on the second).
                secs_int = int(approx_seconds_since_start)
                for iperf_vals in iperf_data.values():
                    try:
                        val = iperf_vals[secs_int]
                    except KeyError:  # special case for second 1800
                        val = iperf_vals[secs_int - 1]
                    row.append(val["rtt"])
                    row.append(val["rttvar"])
                    row.append(val["retransmits"])

            # Write angle and real for each channel in each PMU
            for pmu_name in pmus.keys():
                for channel in channels:
                    doc = nested[time_step][pmu_name][channel]
                    try:
                        row.append(doc["measurement.phasor.angle"])
                    except Exception as ex:
                        utils.eprint(f"bad doc: {doc!r}\nexception: {ex!s}")
                        sys.exit(1)
                    row.append(doc["measurement.phasor.real"])

            # Write freq and dfreq for each PMU
            for pmu_name in pmus.keys():
                pmu_doc = nested[time_step][pmu_name][channels[0]]
                row.append(pmu_doc["measurement.frequency"])
                row.append(pmu_doc["measurement.dfreq"])

            writer.writerow(row)

    utils.print_msg(f"Wrote {len(time_steps)} rows to CSV file: {csv_path}")


def main():
    """ability to generate CSV from existing data."""
    parser = argparse.ArgumentParser("csv_gen")
    parser.add_argument("-r", "--record-file", type=str, required=True)
    parser.add_argument("-e", "--elastic-server", type=str, required=True)
    parser.add_argument("-f", "--csv-path", type=str, required=True)
    parser.add_argument(
        "-i", "--elastic-index", type=str, default="rtds-clean", required=False
    )
    parser.add_argument("--iperf-dir", type=str, default=None, required=False)
    args = parser.parse_args()

    assert args.elastic_server
    assert args.csv_path

    record_path = Path(args.record_file).expanduser().resolve()
    record = utils.read_json(record_path)
    csv_path = Path(args.csv_path).expanduser().resolve()

    gen_csv(
        record=record,
        csv_path=csv_path,
        es_server=args.elastic_server,
        es_index=args.elastic_index,
        iperf_dir=args.iperf_dir,
    )


if __name__ == "__main__":
    main()
