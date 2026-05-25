$c = @''
# config.py content here
'@
[IO.File]::WriteAllText($pwd.Path + "\crypto_monitor\config.py", $c, [Text.Encoding]::UTF8)
