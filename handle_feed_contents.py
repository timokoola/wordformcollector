from flask import Flask, request

import json
import os
import time
from typing import List
from xml.dom.minidom import Element
import jsonlines
import opml
import feedparser
import libvoikko

app = Flask(__name__)


def extract_feed_urls(outline: Element) -> List[str]:
    feeds = outline[0]
    feedUrls = []
    for feed in feeds:
        feedUrls.append(feed.xmlUrl)
    return feedUrls


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
    print(f"Removed {pre_len - len(kotus)} duplicates")
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
    opml_file = os.environ["OPML_FILE"]
    # read bucket name from environment variable
    bucket_name = os.environ["BUCKET_NAME"]

    # download kotus and opml files from gcp bucket
    os.system(f"gsutil cp gs://{bucket_name}/kotus_all.json .")
    os.system(f"gsutil cp gs://{bucket_name}/{opml_file} .")

    # verify that the files were downloaded
    # and error out if they were not
    if not os.path.exists("kotus_all.json"):
        print("kotus_all.json not found")
        exit(1)

    if not os.path.exists(opml_file):
        print(f"{opml_file} not found")
        exit(1)

    # epoc timestamped file name in feeds directory
    output = f"/feeds/{int(time.time())}.jsonl"

    # ensure the feeds directory exists
    if not os.path.exists("feeds"):
        os.makedirs("feeds")

    # parse the opml file
    outline = opml.parse(opml_file)

    print("Parsing OPML file...")
    # get the list of feeds
    feedUrls = extract_feed_urls(outline)

    full_text = ""
    # for reporting purposes
    feed_count = 0

    for feed in feedUrls:
        text, count = extraxt_text_from_feed(feed)
        full_text += text
        feed_count += count

    # normalize the text
    full_text = " ".join(full_text.lower().split())

    # get kotus data
    kotus = get_kotus_data()
    # set to determine if we need to process the word
    unique_words = set([w["word"] for w in kotus])
    # kotus words as a dictionary for faster lookup
    kotus_dict = dict([(x["word"], x) for x in kotus])

    # run full text through voikko
    voikko = libvoikko.Voikko("fi")
    word_forms = [
        (word, voikko.analyze(word))
        for word in full_text.split()
        if len(voikko.analyze(word)) > 0
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
