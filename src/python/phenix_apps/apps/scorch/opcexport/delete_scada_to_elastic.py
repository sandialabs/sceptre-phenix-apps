#!/usr/bin/env python3

import argparse

from elasticsearch import Elasticsearch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--elasticsearch_endpoint")
    args = parser.parse_args()

    es = Elasticsearch(args.elasticsearch_endpoint)
    es.indices.delete(index='opc-dirty*')
    es.close()


if __name__ == "__main__":
    main()
