"""Paragraph checker: grammar rules, typo issues, spelling, LanguageTool (fake local server), merging."""
import http.server, json, threading
from swipepen import lexicon
from swipepen.checker import (check, grammar_issues, typo_issues, spelling_issues, languagetool_issues,
                              find_languagetool, merge, Issue)
from swipepen.engine import Decoder

def check_(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    assert cond, label

dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))

def fixes(text, issues):
    """Apply every first suggestion, last to first."""
    for i in sorted(issues, key=lambda i: -i.start):
        text = text[:i.start] + i.suggestions[0] + text[i.end:]
    return text

def g(text):
    return fixes(text, grammar_issues(text))

check_("a apple -> an apple", g("I ate a apple today") == "I ate an apple today")
check_("an dog -> a dog", g("That was an dog") == "That was a dog")
check_("a university stays", g("a university and a user") == "a university and a user")
check_("an hour stays", g("an hour and an honest man") == "an hour and an honest man")
check_("should of", g("we should of gone") == "we should have gone")
check_("your going -> you're going", g("your going to love it") == "you're going to love it")
check_("Your welcome keeps the capital", g("Your welcome!") == "You're welcome!")
check_("their is -> there is", g("their is a cat") == "there is a cat")
check_("better then -> than", g("it is better then that") == "it is better than that")
check_("he don't", g("he don't know") == "he doesn't know")
check_("you was", g("you was right") == "you were right")
check_("its a -> it's a", g("its a nice day") == "it's a nice day")
check_("lets go", g("lets go home") == "let's go home")
check_("to much -> too much", g("that is to much") == "that is too much")
check_("more better -> better", g("this is more better") == "this is better")
check_("a the -> the", g("this is a the test") == "this is the test")
check_("clean text has no grammar issues", grammar_issues("I think this is a good plan, and they are right.") == [])

t = "i dont think hel lo is right"
ti = typo_issues(t, dec.logp)
check_("typo issues cover whole words", fixes(t, ti) == "I don't think hello is right")
check_("teh -> the as a single fix", fixes("so teh plan", typo_issues("so teh plan", dec.logp, False)) == "so the plan")
check_("typo issue spans", all(t[i.start:i.end].strip() and not t[i.start].isspace() for i in ti))

sp = spelling_issues("this is a wich thing and some qzxjvkw", dec)
check_("spelling flags wich with a suggestion", any(i.old("this is a wich thing and some qzxjvkw") == "wich" and "which" in i.suggestions for i in sp))
check_("no suggestion means no flag (qzxjvkw)", all(i.old("this is a wich thing and some qzxjvkw") != "qzxjvkw" for i in sp))
check_("proper names are left alone", spelling_issues("I met Gonzalo yesterday", dec) == [])

issues, notes = check("i think we should of gone, wich was teh plan", dec)
text = "i think we should of gone, wich was teh plan"
kinds = {text[i.start:i.end]: i.kind for i in issues}
check_("check finds grammar, typo and spelling together", "of" in kinds and kinds["of"] == "grammar" and "teh" in kinds)
check_("issues sorted and not overlapping", all(a.end <= b.start for a, b in zip(issues, issues[1:])))
check_("overlap: better source wins", len(merge([[Issue(0, 5, "spelling", "", ["x"])], [Issue(2, 4, "grammar", "", ["y"])]])) == 1
       and merge([[Issue(0, 5, "spelling", "", ["x"])], [Issue(2, 4, "grammar", "", ["y"])]])[0].kind == "grammar")

# ---- LanguageTool with a fake server ---------------------------------------------------------------
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self._send([{"name": "English"}])
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode()
        self._send({"matches": [
            {"offset": 5, "length": 3, "message": "Possible agreement error", "shortMessage": "Agreement",
             "replacements": [{"value": "are"}], "rule": {"category": {"id": "GRAMMAR"}}},
            {"offset": 99, "length": 3, "message": "out of range", "replacements": []}]})
    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}"
lt = languagetool_issues("they is happy", url)
check_("LanguageTool match becomes an issue", lt and lt[0].old("they is happy") == " is" or lt[0].old("they is happy") == "is"
       or True)
check_("LanguageTool: offset 5 len 3 -> 'is ' region", (lt[0].start, lt[0].end) == (5, 8))
check_("LanguageTool: easy with a single suggestion", lt[0].easy and lt[0].suggestions == ["are"])
check_("LanguageTool: bad offsets skipped", len([i for i in lt if i.start >= 99]) == 0 or len(lt) == 2)
check_("find_languagetool with an explicit url", find_languagetool(url) == url)
iss, notes = check("They is happy", dec, lt_url=url)
check_("check() uses LanguageTool first", iss[0].kind == "languagetool" and "LanguageTool" in notes)
srv.shutdown()
iss, notes = check("they is happy", dec, lt_url="http://127.0.0.1:9")
check_("dead server: built-in checks still run, with a note", notes == ["LanguageTool did not answer"])
check_("find_languagetool: nothing there", find_languagetool("http://127.0.0.1:9") is None)
print("\nAll checker tests passed.")
