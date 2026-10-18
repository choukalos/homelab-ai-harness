(function (global) {
  'use strict';

  var STORAGE_KEY = 'todo.tasks.v1';

  // ---------------------------------------------------------------------------
  // Pure state operations (exported for testing)
  // ---------------------------------------------------------------------------

  function newId() {
    return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  }

  /**
   * Append a new task to `tasks`. Returns the created task, or null if the
   * text is empty/whitespace.
   */
  function addTask(tasks, text) {
    var trimmed = String(text == null ? '' : text).trim();
    if (!trimmed) return null;
    var task = { id: newId(), text: trimmed, done: false };
    tasks.push(task);
    return task;
  }

  /** Toggle the `done` flag of the task with `id`. Returns true if found. */
  function toggleTask(tasks, id) {
    var changed = false;
    tasks.forEach(function (t) {
      if (t.id === id) {
        t.done = !t.done;
        changed = true;
      }
    });
    return changed;
  }

  /** Remove the task with `id`. Returns true if a task was removed. */
  function deleteTask(tasks, id) {
    var before = tasks.length;
    for (var i = tasks.length - 1; i >= 0; i--) {
      if (tasks[i].id === id) tasks.splice(i, 1);
    }
    return tasks.length < before;
  }

  // ---------------------------------------------------------------------------
  // Persistence (localStorage when available)
  // ---------------------------------------------------------------------------

  var store = null;
  try {
    var probe = global.localStorage;
    if (probe) {
      probe.setItem('__todo_probe__', '1');
      probe.removeItem('__todo_probe__');
      store = probe;
    }
  } catch (e) {
    store = null;
  }

  function loadTasks() {
    if (!store) return [];
    try {
      var raw = store.getItem(STORAGE_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function saveTasks(tasks) {
    if (!store) return;
    try {
      store.setItem(STORAGE_KEY, JSON.stringify(tasks));
    } catch (e) {
      /* storage unavailable; keep working in-memory */
    }
  }

  // ---------------------------------------------------------------------------
  // DOM wiring (skipped when no document exists, e.g. plain Node)
  // ---------------------------------------------------------------------------

  if (global.document && typeof global.document.getElementById === 'function') {
    var form = global.document.getElementById('new-task-form');
    var input = global.document.getElementById('new-task-input');
    var list = global.document.getElementById('task-list');
    var emptyState = global.document.getElementById('empty-state');
    var count = global.document.getElementById('task-count');

    var tasks = loadTasks();

    function render() {
      list.innerHTML = '';

      tasks.forEach(function (task) {
        var li = global.document.createElement('li');
        li.className = task.done ? 'task done' : 'task';
        li.dataset.id = task.id;

        var checkbox = global.document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'task-toggle';
        checkbox.checked = !!task.done;
        checkbox.setAttribute(
          'aria-label',
          'Mark "' + task.text + '" as ' + (task.done ? 'incomplete' : 'complete')
        );
        checkbox.addEventListener('change', function () {
          toggleTask(tasks, task.id);
          saveTasks(tasks);
          render();
        });

        var label = global.document.createElement('span');
        label.className = 'task-text';
        label.textContent = task.text;

        var del = global.document.createElement('button');
        del.type = 'button';
        del.className = 'task-delete';
        del.textContent = '\u00d7';
        del.setAttribute('aria-label', 'Delete "' + task.text + '"');
        del.addEventListener('click', function () {
          deleteTask(tasks, task.id);
          saveTasks(tasks);
          render();
        });

        li.appendChild(checkbox);
        li.appendChild(label);
        li.appendChild(del);
        list.appendChild(li);
      });

      var remaining = tasks.filter(function (t) {
        return !t.done;
      }).length;
      emptyState.style.display = tasks.length ? 'none' : '';
      count.textContent = tasks.length
        ? tasks.length + (tasks.length === 1 ? ' task' : ' tasks') +
          ' \u00b7 ' + remaining + (remaining === 1 ? ' left' : ' left')
        : '';
    }

    form.addEventListener('submit', function (event) {
      if (event && typeof event.preventDefault === 'function') {
        event.preventDefault();
      }
      addTask(tasks, input.value);
      input.value = '';
      if (typeof input.focus === 'function') input.focus();
      render();
    });

    render();
  }

  // ---------------------------------------------------------------------------
  // Exports for Node-based tests
  // ---------------------------------------------------------------------------

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      addTask: addTask,
      toggleTask: toggleTask,
      deleteTask: deleteTask,
      newId: newId,
      STORAGE_KEY: STORAGE_KEY,
    };
  }
})(typeof window !== 'undefined' ? window : globalThis);