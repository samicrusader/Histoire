/**
 * File listing sort script largely based on sortable v2.3.2 (<https://github.com/tofsjonas/sortable>, Copyleft 2017 Jonas Earendel)
 * https://github.com/samicrusader/Histoire
 * I'm not quoting the whole Unlicense in this file: <https://choosealicense.com/licenses/unlicense/>
 *
 * Feel free to take this script for your file indexer.
 */

const table = $(".file-listing");

function findElementRecursive(element, tag) {
    // allows for elements inside TH
    return element.nodeName === tag ? element : findElementRecursive(element.parentNode, tag);
}

function reClassify(element, dir) {
    // strips ascending/descending sort classes, replacing with the right class
    element.classList.remove('sort-desc');
    element.classList.remove('sort-asc');
    if (dir)
        element.classList.add(dir);
}

function getValue(element) {
    // this checks if the `data-sort` HTML attribute is used, sorting using its value if it exists, otherwise using the `textContent`
    // this is modified to make a tad more sense
    if (element.hasAttribute('data-sort')) { return element.dataset.sort; }
    else { return element.textContent; }
}

function sortOnColumnClick(e) {
    let element = findElementRecursive(e.target, 'TH');
    let thead = table.find('thead')[0];

    // Check conditions before sorting for sanity
    if (thead.nodeName !== 'THEAD' && // sortable only triggered in `thead`
        !table[0].classList.contains('file-listing') && // also only trigger on file-listing as to not affect tables included via markdown/html headers
        element.classList.contains('no-sort')) { return; } // .no-sort is now core functionality, no longer handled in CSS

    // Call main table sorting function
    tableSort(element)
}

function tableSort(element, dir = null) {
    // Table elements
    let tr = element.parentNode;
    let tbody = table.find("tbody")[0];

    // Reset thead cells and get column index
    let column_index_1;
    let nodes = tr.cells;
    let tiebreaker_1 = parseInt(element.dataset.sortTbr);
    for (let i = 0; i < nodes.length; i++) {
        if (nodes[i] === element) {
            column_index_1 = parseInt(element.dataset.sortCol) || i;
        }
        else {
            reClassify(nodes[i], '');
        }
    }

    // Check if we have a sort type passed in already
    if (dir === null) {
        // if not, check if the element has already been sorted
        if (element.classList.contains('sort-desc')) { dir = 'sort-asc'; }
        else if (element.classList.contains('sort-asc')) { dir = 'sort-desc'; }
        else {
            // Otherwise, sort ascending or descending based on which column is sorted by
            if (element.classList.contains('filename') || element.classList.contains('file-type')) { dir = 'sort-asc'; }
            else if (element.classList.contains('date-modified') || element.classList.contains('file-size')) { dir = 'sort-desc'; }
            else { return; } // return because we shouldn't be sorting otherwise
        }
    }
    reClassify(element, dir); // Update the `th` class accordingly

    // Store sort type to be used in other pages
    let stor_dir = dir.split('-')[1];
    let stor_type = 'name'; // default to `name`
    if (element.classList.contains('date-modified')) { stor_type = 'date'; }
    else if (element.classList.contains('file-size')) { stor_type = 'size'; }
    localStorage.setItem("histoire-sort", stor_type+'/'+stor_dir);

    // Actual sorting starts here
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

    let rows = [].slice.call(tbody.rows, 0); // Put the array rows in an array, so we can sort them...
    // Sort them using Array.prototype.sort()
    rows.sort(function (a, b) {
        let bool = compare_1(a, b, column_index_1);
        return bool === 0 && !isNaN(tiebreaker_1) ? compare_1(a, b, tiebreaker_1) : bool;
    });
    let clone_tbody = tbody.cloneNode(); // Make an empty clone of existing table body
    clone_tbody.append.apply(clone_tbody, rows); // Put the sorted rows inside the clone
    table[0].replaceChild(clone_tbody, tbody); // And finally replace the unsorted tbody with the sorted one
}

table.find("thead")[0].addEventListener('click', sortOnColumnClick); // Sort on click
(function() {
    $(document).ready(function() {
        // Sort on page load from stored variable
        let sort_val = localStorage.getItem("histoire-sort");
        if (sort_val) {
            if (sort_val === 'asc/name') {
                return; // Don't do anything if sorting ascending by name, as the file server index has already done this for us. It just wastes resources.
            }
            let [stor_type, stor_dir] = sort_val.split('/');
            let element;
            if (stor_type === 'name') { element = $('table.file-listing > thead > tr > th.filename')[0]; }
            else if (stor_type === 'date') { element = $('table.file-listing > thead > tr > th.date-modified')[0]; }
            else if (stor_type === 'size') { element = $('table.file-listing > thead > tr > th.file-size')[0]; }
            tableSort(element, 'sort-'+stor_dir);
        }
    })}
)();