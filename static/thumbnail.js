(function() {
    document.onreadystatechange = function() {
        if (document.readyState === 'interactive') {
            $('img.file-listing.thumbnail').each(function () {
                this.addEventListener('error', function (x) {
                    x.currentTarget.outerHTML = '<span class="fiv-sqo fiv-icon-bin"></span>';
                });
            });
        }
    };
    $(document).ready(function () {
        $('.file-listing.thumbnail').each(function () {
            this.addEventListener("mouseover", function (x) {
                let mouse_pos_y = x.currentTarget.getBoundingClientRect().top; // This is where the mouse currently is positioned to trigger the tooltip
                let mouse_pos_x = (x.currentTarget.getBoundingClientRect().right + window.scrollX + 10)
                let thumb_url = x.currentTarget.getAttribute('src').replace('&scale=true', '&scale=false'); // Get larger thumbnail

                // Create tooltip object
                const tooltip = document.createElement('div');
                tooltip.className = 'ui file-listing tooltip';
                tooltip.style.visibility = 'hidden'; // Force the tooltip to be hidden until we can run our image onload code, this makes the showing of the viewport cleaner as it is resized

                // Create image object and set tooltip position when loaded
                let image_obj = new Image();
                image_obj.src = thumb_url;
                image_obj.onload = function() {
                    // Calculate vertical placement of the image
                    let tooltip_y;
                    if ((mouse_pos_y + tooltip.clientHeight) > document.documentElement.clientHeight) { // If (the mouse position + tooltip height) is more than the viewport's height
                        tooltip_y = (document.documentElement.clientHeight - tooltip.clientHeight); // Set the tooltip's top position to the viewport height minus the tooltip height
                    } else { // otherwise
                        tooltip_y = mouse_pos_y // Set the tooltip's top position to the mouse position
                    }
                    tooltip_y += window.scrollY // Account for scrolled viewports
                    tooltip.style.top = tooltip_y + 'px';
                    tooltip.style.left = mouse_pos_x + 'px';
                    tooltip.style.visibility = 'initial'; // Show tooltip
                };
                tooltip.appendChild(image_obj); // Attach image object to tooltip
                x.currentTarget.parentElement.appendChild(tooltip);
            });
            this.addEventListener("mouseout", function (x) {
                let tooltip = $('.ui.file-listing.tooltip')[0];
                x.currentTarget.parentElement.removeChild(tooltip);
            });
        });
    });
})();