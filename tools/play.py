"""
An internal CLI script to play and add audio from the local server.
Maybe this can be an add-on (or part of one) later?

Requirements:
- requests library (`pip install requests`)
- mpv
- 'anki' command:
    - Anki-Connect (with Anki open)

WARNING:
- Hard coded to use "JP Mining Note" (TODO: make configurable)
- Requires *nix systems (as `/tmp/` and `mpv` is hard coded) (TODO: make configurable)

Usage:

`anki` command:
    - attempts to find a unique card
    - gets reading from WordReading
`current` command:
    - equivalent of `anki`, but uses the current card as shown on the reviewer screen.
`local` command:
    - directly queries the server with the word (and optionally, reading)
    - cannot add the result to any card, can only play

Usage (audio selector):

> 0
    - play the audio at index 0
> 3
    - play the audio at index 3
> a
    - adds the audio with index 0 to the card (if `anki` or `current`)
> a3
    - adds the audio with index 3 to the card (if `anki` or `current`)
> e
    - exit

"""

import re
import sys
import json
import shlex
import urllib
import argparse
import subprocess

from pathlib import Path
from time import localtime, strftime
from urllib.parse import urlparse

import requests



rx_PLAIN_FURIGANA = re.compile(r" ?([^ >]+?)\[(.+?)\]")



# taken from https://github.com/FooSoft/anki-connect#python
def request(action: str, **params):
    return {"action": action, "params": params, "version": 6}


def invoke(action: str, **params):
    requestJson = json.dumps(request(action, **params)).encode("utf-8")
    response = json.load(
        urllib.request.urlopen(
            urllib.request.Request("http://localhost:8765", requestJson)
        )
    )
    if len(response) != 2:
        raise Exception("response has an unexpected number of fields")
    if "error" not in response:
        raise Exception("response is missing required error field")
    if "result" not in response:
        raise Exception("response is missing required result field")
    if response["error"] is not None:
        raise Exception(response["error"])
    return response["result"]



def get_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')

    anki = subparsers.add_parser("anki")
    anki.add_argument("word", type=str)
    anki.add_argument("--key", action="store_true", help="search key instead of word field")
    anki.add_argument("--db-search", nargs=2, type=str, default=(None, None), help="search the specified word and reading instead")

    local = subparsers.add_parser("local")
    local.add_argument("word", type=str)
    local.add_argument("--reading", type=str, default=None)

    current = subparsers.add_parser("current") # anki current
    current.add_argument("--db-search", nargs=2, type=str, default=(None, None), help="search the specified word and reading instead")

    return parser.parse_args()

def plain_to_kana(text: str):
    result = text.replace("&nbsp;", ' ')
    return rx_PLAIN_FURIGANA.sub(r"\2", result)

def os_cmd(cmd):
    # shlex.split used for POSIX compatibility
    return cmd if sys.platform == "win32" else shlex.split(cmd)


def send_audio(url: str, note_id: int, word: str, reading: str):
    suffix = url[url.rfind("."):]
    source = Path(urlparse(url).path).parts[1] # crazy hack to get the top most directory

    file_name = f"local_audio_{source}_{word}_{reading}_" + strftime("%Y-%m-%d-%H-%M-%S", localtime()) + suffix
    print(file_name)

    audio_data = [{
        "url": url,
        "filename": file_name,
        "fields": [
            "WordAudio"
        ]
    }]

    invoke("updateNoteFields", note={
        "id": note_id,
        "fields": {
            "WordAudio": "",
        },
        "audio": audio_data
    })


def pretty_print_sources(sources):
    for i, source in enumerate(sources):
        print("", i, source["name"])


def main():
    args = get_args()
    command = args.command
    note_id = None

    if command == "anki" or command == "current":
        if command == "anki":
            field = "Key" if args.key else "Word"
            note_ids = invoke("findNotes", query=f'"note:JP Mining Note" "{field}:{args.word}"')
            notes_info = invoke("notesInfo", notes=note_ids)
            if len(note_ids) > 1:
                print("Multiple cards found!")
                print([info["fields"]["Key"]["value"] for info in notes_info])
                return
            if len(note_ids) < 1:
                print("No cards found!")
                return

            note_id = note_ids[0]
            note_info = notes_info[0]
        else: # current
            note_info = invoke("guiCurrentCard")
            note_id = invoke("cardsToNotes", cards=[note_info["cardId"]])[0]

        db_word, db_reading = args.db_search
        if db_word is None or db_reading is None:
            # use word from Anki
            word = note_info["fields"]["Word"]["value"]
            word_reading = note_info["fields"]["WordReading"]["value"]
            reading = plain_to_kana(word_reading)
        else:
            # we search the database with the field
            word = db_word
            reading = db_reading

        print(word, reading)

    else: # local
        word = args.word
        reading = args.reading # note: can be None!


    if reading is None:
        query_url = f'http://localhost:5050/?term={word}'
    else:
        query_url = f'http://localhost:5050/?term={word}&reading={reading}'
    r = requests.get(query_url)

    sources = r.json().get("audioSources")

    exit_loop = False
    while not exit_loop:
        print()
        pretty_print_sources(sources)
        print()

        user_input = input("> ").strip()
        try:
            if user_input == "e":
                exit_loop = True
            elif user_input == "":
                pass
            elif user_input.startswith("a"): # add audio
                if user_input == "a":
                    idx = 0
                else:
                    idx = int(user_input[1:])

                if 0 <= idx < len(sources):
                    url = sources[idx]["url"]
                else:
                    print(f"Invalid index: {idx}")
                    continue

                assert note_id is not None
                send_audio(url, note_id, word, reading)
                exit_loop = True

            else: # play audio
                idx = int(user_input)

                if 0 <= idx < len(sources):
                    url = sources[idx]["url"]
                else:
                    print(f"Invalid index: {idx}")
                    continue

                print(url)
                r2 = requests.get(url)
                with open("/tmp/local_audio", "wb") as f:
                    f.write(r2.content)

                subprocess.run(os_cmd("mpv /tmp/local_audio"), encoding="utf8")
        except Exception as e:
            #print(e)
            raise e


if __name__ == "__main__":
    main()

