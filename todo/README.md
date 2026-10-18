# Todo List

A small single-page todo list web app. Add tasks, toggle them complete, and delete them. Tasks persist in `localStorage`.

## Features

- **Add** a task via the form (Enter or the Add button)
- **Toggle complete** via the checkbox (strikethrough when done)
- **Delete** a task via the × button
- Persists across reloads in `localStorage`
- No dependencies, no build step

## Run

Open `index.html` directly in a browser, or serve the directory:

```sh
cd todo
python3 -m http.server 8080
# then visit http://localhost:8080
```

## Test

```sh
node test/dom-shim.test.js
```