(function() {
    $(document).ready(function() {
        $("table th").click(function(e) {
            localStorage.setItem("table_sort", Array.from(e.target.parentElement.children).indexOf(e.target).toString());
        });
        const ts = localStorage.getItem("table_sort");
        if (ts !== null && ts.length > 0) {
            document.querySelectorAll("table th")[parseInt(ts)].setAttribute("data-sort-default", "");
        }
        new Tablesort(document.querySelector("table"), {
            descending: false,
        });
    })
})();