from flask import Flask

import json
import os
import time
from typing import List
import jsonlines
import feedparser
import libvoikko
from logging.config import dictConfig

dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)


app = Flask(__name__)
# enable debugging
app.config["DEBUG"] = True


def extraxt_text_from_feed(feed):
    feed = feedparser.parse(feed)
    feed_entries = feed.entries
    feed_count = len(feed_entries)
    full_text = ""
    for entry in feed_entries:
        full_text += entry.title + " " + entry.description
        if "summary" in entry:
            full_text += " " + entry.summary
        if "content" in entry:
            for content in entry.content:
                full_text += " " + content.value
    return full_text, feed_count


# get kotus data
def get_kotus_data() -> dict:
    f = open("kotus_all.json")
    kotus = json.loads(f.read())
    pre_len = len(kotus)
    # remove duplicates
    kotus = list({v["word"]: v for v in kotus}.values())
    # report how many duplicates were removed
    app.logger.info(f"Removed {pre_len - len(kotus)} duplicates")
    f.close()
    return kotus


def flatten_voikko_results(word_forms):
    flat_words = []
    for item in word_forms:
        word = item[0]
        for i in item[1]:
            flat_words.append({"BOOKWORD": word.lower(), **i})
    return flat_words


def get_book_words_in_kotus(kotus_dict, flat_words):
    gutenberg_results = []
    for bw in flat_words:
        baseform = bw["BASEFORM"]
        if baseform in kotus_dict and kotus_dict[baseform]["tn"] < 53:
            gutenberg_results.append({**kotus_dict[baseform], **bw})
    return gutenberg_results


def extract_unique_words(unique_words, gutenberg_results):
    unique_gutenberg_words = []
    for item in gutenberg_results:
        # if the word is not in the unique words set
        # add it to the results list
        # and add it to the unique words set
        key = item["BOOKWORD"]
        if key not in unique_words:
            unique_gutenberg_words.append(item)
            unique_words.add(key)
    return unique_gutenberg_words


@app.route("/", methods=["POST"])
def main():
    # read opml file name from environment variable
    # changed it to a txt file for easier editing and parsing
    opml_file = os.environ["OPML_FILE"]
    # read bucket name from environment variable
    bucket_name = os.environ["BUCKET_NAME"]

    # download kotus and opml files from gcp bucket
    os.system(f"gsutil cp gs://{bucket_name}/kotus_all.json .")
    os.system(f"gsutil cp gs://{bucket_name}/{opml_file} .")
    # also download the unique words file
    os.system(f"gsutil cp gs://{bucket_name}/unique_words.json .")

    # verify that the files were downloaded
    # and error out if they were not
    if not os.path.exists("kotus_all.json"):
        app.logger.error("kotus_all.json not found")
        exit(1)

    if not os.path.exists(opml_file):
        app.logger.error(f"{opml_file} not found")
        exit(1)

    # epoc timestamped file name in feeds directory
    output = f"feeds/{int(time.time())}.jsonl"

    # ensure the feeds directory exists
    if not os.path.exists("feeds"):
        os.makedirs("feeds")

    app.logger.info("Parsing OPML file...")
    # get the list of feeds from the now txt file
    with open(opml_file) as f:
        feedUrls = [line.rstrip() for line in f]

    app.logger.info(f"Found {len(feedUrls)} feeds in OPML file...")

    full_text = ""
    # for reporting purposes
    feed_count = 0

    for feed in feedUrls:
        app.logger.info(f"Processing feed {feed}...")
        text, count = extraxt_text_from_feed(feed)
        full_text += text
        feed_count += count

    # normalize the text
    full_text = " ".join(full_text.lower().split())

    # get kotus data
    kotus = get_kotus_data()
    # set to determine if we need to process the word
    # use the unique_words.json from the bucket
    # to avoid processing words that have already been processed
    with open("unique_words.json") as f:
        json_data = json.load(f)
        # extract the unique words from the json
        already_processed = set(json_data["words"])

    unique_words = set([w["word"] for w in kotus])
    # kotus words as a dictionary for faster lookup
    kotus_dict = dict([(x["word"], x) for x in kotus])

    # run full text through voikko
    voikko = libvoikko.Voikko("fi")
    word_forms = [
        (word, voikko.analyze(word))
        for word in full_text.split()
        if word not in already_processed and len(voikko.analyze(word)) > 0
    ]

    flat_words = flatten_voikko_results(word_forms)
    # words from current book that have been run through voikko
    # as a set for faster lookup
    book_bw = set([w["BASEFORM"] for w in flat_words])
    # words from gutenberg that have been run through voikko
    feed_results = get_book_words_in_kotus(kotus_dict, flat_words)
    pre_addition = len(unique_words)
    # extract unique words from gutenberg results
    unique_extracted_words = extract_unique_words(unique_words, feed_results)

    # report added unique words
    print(f"Added {len(unique_extracted_words)} unique words from Feeds", end="\r")

    # write feed text results to the output file
    with jsonlines.open(output, "w") as writer:
        writer.write_all(unique_extracted_words)

    # upload the file to gcp bucket bucket_name
    os.system(f"gsutil cp {output} gs://{bucket_name}")
    return "ok", 200


if __name__ == "__main__":
    # this is a flask app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
