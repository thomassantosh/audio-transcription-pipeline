# COMMIT LOCAL BRANCH CHANGES
branch=$(shell git symbolic-ref --short HEAD)

git-push:
	@read -p "Enter commit message: " msg && git add . && git commit -m "$$msg" && git push -u origin $(branch)
