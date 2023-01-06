// This will be replaced in the future.

(function() {
    $(document).ready(function() {
        const ts = localStorage.getItem("sort");
        if (ts) {
            let sort = ts.split("_")[1]
            switch(ts.split("_")[0]) {
                case "name":
                    col = 1;
                    break
                case "modifiedby":
                    col = 2;
                    break
                case "size":
                    col = 3
                    break
                case _:
                    return
            }
            let htmlcol = document.querySelectorAll("table th")[col];
            htmlcol.setAttribute("aria-sort", sort);
            htmlcol.setAttribute("data-sort-default", "")
        }
        new Tablesort(document.querySelector("table"), {
            descending: false,
        });
        $("table th").click(function(e) {
            setTimeout(function(){
                let col = null;
                let sort = null;
                switch(Array.from(e.target.parentElement.children).indexOf(e.target)) {
                    case 1:
                        col = "name";
                        break
                    case 2:
                        col = "modifiedby";
                        break
                    case 3:
                        col = "size"
                        break
                    case _:
                        return
                }
                // There is some bug in this table sorting library. I have to swap these around. No clue why.
                switch(e.target.getAttribute("aria-sort")) {
                    case "ascending":
                        sort = "descending";
                        break
                    case _:
                        sort = "ascending";
                        break
                }
                let data = col+"_"+sort;
                localStorage.setItem("sort", data);
            }, 500);
        });
    })
})();