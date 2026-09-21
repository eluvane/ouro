foo && bar || baz
cmd <<-'END'
	indented
END
echo $((1+2))
