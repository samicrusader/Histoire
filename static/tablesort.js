/**
 * File listing sort script largely based on sortable v2.3.2 (<https://github.com/tofsjonas/sortable>, Copyleft 2017 Jonas Earendel)
 * https://github.com/samicrusader/Histoire
 * I'm not quoting the whole Unlicense in this file: <http://unlicense.org>
 */

const table = $(".file-listing");

function tablesort(e) {
    function findElementRecursive(element, tag) {
        // allows for elements inside TH
        console.log('findElementRecursive', element, tag);
        return element.nodeName === tag ? element : findElementRecursive(element.parentNode, tag);
    }

    function reClassify(element, dir) {
        // strips asc/desc classes and adds proper sorted class
        element.classList.remove('sort-desc');
        element.classList.remove('sort-asc');
        if (dir)
            element.classList.add(dir);
    }

    function getValue(element) {
        let _a;
        return (_a = element.dataset.sort) !== null && _a !== void 0 ? _a : element.textContent;
    }

    // Variables
    let element = findElementRecursive(e.target, 'TH');
    console.log(element);
    let tr = element.parentNode;
    let thead = table.find('thead')[0];
    let tbody = table.find("tbody")[0]

    if (thead.nodeName !== 'THEAD' && // sortable only triggered in `thead`
        !table[0].classList.contains('file-listing') &&
        element.classList.contains('no-sort')) { console.log('sex'); return; } // .no-sort is now core functionality, no longer handled in CSS

    let column_index_1;
    let nodes = tr.cells;
    let tiebreaker_1 = parseInt(element.dataset.sortTbr);
    // Reset thead cells and get column index
    for (let i = 0; i < nodes.length; i++) {
        if (nodes[i] === element) {
            column_index_1 = parseInt(element.dataset.sortCol) || i;
        }
        else {
            reClassify(nodes[i], '');
        }
    }
    let dir = 'sort-desc';
    // Check if we're sorting ascending or descending
    if (element.classList.contains('sort-desc') ||
        (table[0].classList.contains('asc') &&
        !element.classList.contains('sort-asc')))
    {
        dir = 'sort-asc';
    }
    // Update the `th` class accordingly
    reClassify(element, dir);
    let reverse_1 = dir === 'sort-asc';
    let compare_1 = function (a, b, index) {
        let x = b.cells[index];
        if (x === undefined) {
            return 1;
        }
        let x_value = getValue(x);
        let y = a.cells[index];
        let y_value = getValue(y);
        if (x.classList.contains('parent-dir')) {
            return 1; // Always put parent directory first
        }
        if (x_value === '' && y_value !== '') {
            return -1;
        }
        if (x_value === '' && y_value !== '') {
            return 1;
        }
        let temp = Number(x_value) - Number(y_value);
        let bool = isNaN(temp) ? x_value.localeCompare(y_value, undefined, {numeric: true, sensitivity: 'base'}) : temp;
        return reverse_1 ? -bool : bool;
    };

    // main sort
    let rows = [].slice.call(tbody.rows, 0); // Put the array rows in an array, so we can sort them...
    // Sort them using Array.prototype.sort()
    rows.sort(function (a, b) {
        let bool = compare_1(a, b, column_index_1);
        return bool === 0 && !isNaN(tiebreaker_1) ? compare_1(a, b, tiebreaker_1) : bool;
    });
    // Make an empty clone
    let clone_tbody = tbody.cloneNode();
    // Put the sorted rows inside the clone
    clone_tbody.append.apply(clone_tbody, rows);
    // And finally replace the unsorted tbody with the sorted one
    table[0].replaceChild(clone_tbody, tbody);
}

table.find("thead")[0].addEventListener('click', tablesort); // Sort on click
(function() {$(document).ready(function() {})})(); // Sort on page load