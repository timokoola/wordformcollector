import xmltodict
import json
import collections
import typing
import argparse


def toTn(tn):
    pass


def toLine(item):
    if "s" not in item or "t" not in item:
        return (item["s"], -1, "_")
    word = item["s"]
    type_ = item["t"]
    if isinstance(type_, typing.List):
        result = []
        for t_ in type_:
            tn = int(t_["tn"] if "tn" in t_ else "0")
            av = t_["av"] if "av" in t_ else "_"
            result.append((word, tn, av))
        return result
    else:
        tn = int(type_["tn"] if "tn" in type_ else "0")
        if "av" not in type_:
            av = "_"
        elif (
            isinstance(type_["av"], collections.OrderedDict) and "#text" in type_["av"]
        ):
            av = type_["av"]["#text"]
        else:
            av = type_["av"] if "av" in type_ else "_"
        return (word, tn, av)


def toKey(word):
    return f"{word['tn']}_{word['av']}_{word['word']}"


if __name__ == "__main__":
    # argument parsing

    parser = argparse.ArgumentParser()
    # Download and unzip the file from https://kaino.kotus.fi/sanat/nykysuomi/kotus-sanalista-v1.zip
    parser.add_argument("--kotus-file", type=str, default="kotus-sanalista_v1.xml")
    args = parser.parse_args()

    with open(args.kotus_file, "r") as f:
        kotus_ = f.read()

    kotus = xmltodict.parse(kotus_)

    simple = [
        toLine(x)
        for x in kotus["kotus-sanalista"]["st"]
        if "t" in x and not isinstance(x["t"], typing.List)
    ]
    complex_ = [
        toLine(x)
        for x in kotus["kotus-sanalista"]["st"]
        if "t" in x and isinstance(x["t"], typing.List)
    ]

    d = collections.defaultdict(list)
    for s in simple:
        d[f"{s[1]}{s[2]}"].append({"word": s[0], "tn": s[1], "av": s[2]})
    for c in complex_:
        for s in c:
            d[f"{s[1]}{s[2]}"].append({"word": s[0], "tn": s[1], "av": s[2]})

    full = []
    for k in d.keys():
        for x in d[k]:
            full.append(x)

    # remove non-nouns from the list
    full = [x for x in full if x["tn"] < 52]

    # add key to each item
    for x in full:
        x["key"] = toKey(x)

    # use the key as the key in the dictionary
    full = {x["key"]: x for x in full}

    results = []

    # now remove duplicates
    for k in list(full.keys()):
        line = full[k]
        # delete key
        del line["key"]
        results.append(line)

    with open("kotus_all.json", "w+") as f:
        f.write(json.dumps(results, indent=4, ensure_ascii=False))
