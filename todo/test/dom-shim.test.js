'use strict';

/**
 * Functional tests for the todo app.
 *
 * Runs app.js in Node against a minimal DOM shim, exercising the real DOM
 * code paths: add (form submit), toggle (checkbox change), delete (button
 * click), localStorage persistence, and reload restoration.
 *
 * Usage: node test/dom-shim.test.js
 */

const assert = require('assert');
const path = require('path');

// ---------------------------------------------------------------------------
// Minimal DOM shim (only what app.js uses)
// ---------------------------------------------------------------------------

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parent = null;
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this._listeners = {};
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this.type = '';
    this.className = '';
  }

  set innerHTML(v) {
    if (v === '') {
      this.children = [];
    } else {
      throw new Error('DOM shim only supports clearing innerHTML');
    }
  }

  get innerHTML() {
    return '';
  }

  appendChild(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name];
  }

  addEventListener(type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  }

  dispatch(type, event) {
    (this._listeners[type] || []).forEach((fn) => fn(event || { preventDefault() {} }));
  }

  focus() {}

  querySelector(selector) {
    const cls = selector.replace('.', '');
    return this.children.find((c) => c.className.split(' ').includes(cls));
  }
}

const elementsById = {
  'new-task-form': new Element('form'),
  'new-task-input': new Element('input'),
  'task-list': new Element('ul'),
  'empty-state': new Element('p'),
  'task-count': new Element('p'),
};

globalThis.document = {
  getElementById: (id) => elementsById[id] || null,
  createElement: (tag) => new Element(tag),
};

const backing = new Map();
globalThis.localStorage = {
  getItem: (k) => (backing.has(k) ? backing.get(k) : null),
  setItem: (k, v) => backing.set(k, String(v)),
  removeItem: (k) => backing.delete(k),
};

// ---------------------------------------------------------------------------
// Load the app (its DOM wiring runs immediately on require)
// ---------------------------------------------------------------------------

const core = require(path.join(__dirname, '..', 'app.js'));

const form = elementsById['new-task-form'];
const input = elementsById['new-task-input'];
const list = elementsById['task-list'];
const emptyState = elementsById['empty-state'];
const count = elementsById['task-count'];

function taskItems() {
  return list.children;
}

function itemText(li) {
  return li.querySelector('.task-text').textContent;
}

function itemCheckbox(li) {
  return li.querySelector('.task-toggle');
}

function itemDeleteButton(li) {
  return li.querySelector('.task-delete');
}

// ---------------------------------------------------------------------------
// Pure core logic tests
// ---------------------------------------------------------------------------

{
  const tasks = [];
  const t1 = core.addTask(tasks, '  hello  ');
  assert.ok(t1, 'addTask returns the created task');
  assert.strictEqual(t1.text, 'hello', 'addTask trims text');
  assert.strictEqual(t1.done, false, 'new task is not done');
  assert.strictEqual(tasks.length, 1, 'task appended');

  assert.strictEqual(core.addTask(tasks, '   '), null, 'addTask rejects blank text');
  assert.strictEqual(tasks.length, 1, 'blank text not appended');

  const t2 = core.addTask(tasks, 'second');
  assert.notStrictEqual(t1.id, t2.id, 'task ids are unique');

  assert.strictEqual(core.toggleTask(tasks, t1.id), true, 'toggleTask finds task');
  assert.strictEqual(t1.done, true, 'toggleTask flips done to true');
  core.toggleTask(tasks, t1.id);
  assert.strictEqual(t1.done, false, 'toggleTask flips done back to false');
  assert.strictEqual(core.toggleTask(tasks, 'nope'), false, 'toggleTask false for unknown id');

  assert.strictEqual(core.deleteTask(tasks, t2.id), true, 'deleteTask removes task');
  assert.strictEqual(tasks.length, 1, 'task removed from array');
  assert.strictEqual(core.deleteTask(tasks, 'nope'), false, 'deleteTask false for unknown id');
}

// ---------------------------------------------------------------------------
// UI wiring tests (real DOM code paths)
// ---------------------------------------------------------------------------

// --- Initial state: empty list, empty-state visible ---
assert.strictEqual(taskItems().length, 0, 'starts with an empty list');
assert.strictEqual(emptyState.style.display, '', 'empty state visible when no tasks');
assert.strictEqual(count.textContent, '', 'count empty when no tasks');

// --- ADD: submit the form with a task ---
input.value = 'Buy milk';
form.dispatch('submit');
assert.strictEqual(taskItems().length, 1, 'task appears after add');
assert.strictEqual(itemText(taskItems()[0]), 'Buy milk', 'added task text is correct');
assert.strictEqual(input.value, '', 'input cleared after add');
assert.strictEqual(emptyState.style.display, 'none', 'empty state hidden when tasks exist');
assert.match(count.textContent, /1 task/, 'count shows 1 task');

// --- ADD: blank input is ignored ---
input.value = '   ';
form.dispatch('submit');
assert.strictEqual(taskItems().length, 1, 'blank input adds nothing');

// --- ADD: second task ---
input.value = 'Walk the dog';
form.dispatch('submit');
assert.strictEqual(taskItems().length, 2, 'second task added');
assert.strictEqual(itemText(taskItems()[1]), 'Walk the dog', 'second task text correct');
assert.match(count.textContent, /2 tasks/, 'count shows 2 tasks');

// --- TOGGLE: check the first task's checkbox ---
assert.strictEqual(taskItems()[0].className, 'task', 'new task is not done');
assert.strictEqual(itemCheckbox(taskItems()[0]).checked, false, 'checkbox starts unchecked');
itemCheckbox(taskItems()[0]).checked = true;
itemCheckbox(taskItems()[0]).dispatch('change');
assert.match(taskItems()[0].className, /done/, 'task gets .done class after toggle');
assert.strictEqual(itemCheckbox(taskItems()[0]).checked, true, 'checkbox stays checked after re-render');
assert.match(count.textContent, /1 left/, 'count reflects 1 remaining task');

// --- TOGGLE back ---
itemCheckbox(taskItems()[0]).checked = false;
itemCheckbox(taskItems()[0]).dispatch('change');
assert.strictEqual(taskItems()[0].className, 'task', 'toggling back removes .done');
assert.match(count.textContent, /2 left/, 'count back to 2 remaining');

// --- PERSISTENCE: state saved to localStorage ---
const saved = JSON.parse(localStorage.getItem(core.STORAGE_KEY));
assert.strictEqual(saved.length, 2, 'two tasks persisted');
assert.strictEqual(saved[0].text, 'Buy milk', 'persisted task text intact');
assert.strictEqual(saved[0].done, false, 'persisted done flag intact');

// --- DELETE: click the delete button of the second task ---
itemDeleteButton(taskItems()[1]).dispatch('click');
assert.strictEqual(taskItems().length, 1, 'task removed after delete');
assert.strictEqual(itemText(taskItems()[0]), 'Buy milk', 'remaining task is the first one');
assert.match(count.textContent, /1 task/, 'count updated after delete');

const savedAfterDelete = JSON.parse(localStorage.getItem(core.STORAGE_KEY));
assert.strictEqual(savedAfterDelete.length, 1, 'delete persisted to storage');

// --- Reload simulation: re-require the app, expect tasks restored from storage ---
delete require.cache[require.resolve(path.join(__dirname, '..', 'app.js'))];
require(path.join(__dirname, '..', 'app.js'));
assert.strictEqual(taskItems().length, 1, 'task restored from storage on reload');
assert.strictEqual(itemText(taskItems()[0]), 'Buy milk', 'restored task text intact');

// --- Delete the last task: empty state returns ---
itemDeleteButton(taskItems()[0]).dispatch('click');
assert.strictEqual(taskItems().length, 0, 'last task deleted');
assert.strictEqual(emptyState.style.display, '', 'empty state visible again');
assert.strictEqual(count.textContent, '', 'count cleared when no tasks');

console.log('PASS: all todo app tests passed (add, toggle, delete, persistence, reload)');