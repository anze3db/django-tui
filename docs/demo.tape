# The README's demo, recorded with VHS (https://github.com/charmbracelet/vhs): `just demo` saves it as
# docs/images/<next version>/demo.gif and points the README at it.

Require uv
Set Shell "bash"
Set FontSize 18
Set Width 1400
Set Height 820
Set Padding 16
Set WindowBar Colorful
Set Framerate 20
Set TypingSpeed 75ms
Env COLORTERM "truecolor"

# A fresh database with a few polls
Hide
Type "cd tests && rm -f db.sqlite3 && uv run python manage.py migrate -v0 && uv run python manage.py loaddata demo -v0 && clear"
Enter
Sleep 8s
Type "uv run python manage.py tui"
Enter
Sleep 4s
Show
Sleep 1s

# The command name filters the list, the arguments fill in the form
Type "showmig"
Sleep 1s
Type "rations polls"
Sleep 2s

# Enter runs it without leaving the TUI
Enter
Sleep 3s
Enter
Sleep 1s

# Edit the options in the form, and the command updates
Escape
Sleep 500ms
Type "closepoll 1"
Sleep 1s
Tab
Sleep 500ms
Tab
Sleep 500ms
Space
Sleep 2s
Ctrl+R
Sleep 3s
Enter
Sleep 1s

# The shell, with your models imported
Ctrl+J
Sleep 1s
Type "Question.objects.filter(is_open=True"
Sleep 500ms
Ctrl+R
Sleep 3s

# Press ctrl+c twice to quit
Ctrl+C
Sleep 500ms
Ctrl+C
Sleep 1s
