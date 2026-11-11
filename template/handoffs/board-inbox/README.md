# Board inbox

Lanes never edit the board. Each lane appends its asks for the owner to its own file here,
`handoffs/board-inbox/<lane>.md`, and pushes with `tools/hub_push.sh`. One writer (the main session, or a
scheduled tick) runs `python3 tools/board.py fold`, which builds `board/BOARD.md` and marks entries FOLDED.

Entry format (one per ask, newest at the bottom; `tools/board.py add` writes it for you):

    ## <lane>-<n> | <send|decide|do> | <p1 today, p2 this week, p3 whenever> | OPEN
    title: <one plain line>
    why: <one or two sentences>
    links: <label> <url>            (optional, one per line)
    options: A: ... (recommended) / B: ...   (decide only)
    send:                            (send only: the full message, indented four spaces)
        To: ada@example.com
        Subject: ...
        <body exactly as it will go out>

Status words in the heading: OPEN, FOLDED, HELD, ANSWERED, SENT, DONE.

Rules:
- One open message per person. `tools/lock.py dupes` lists anyone with two open sends; merge them into one
  message with short labelled parts before folding (fold refuses until then).
- Hold, do not pile on: if the owner's last message to someone is unanswered, write the entry as HELD with
  "waiting on <name>'s reply" unless they asked for something or set a deadline.
- No private detail here (health, money, family, other people's addresses). Write "private: see <local path>".
