(function() {
    $(document).ready(function () {
        $('.file-listing.thumbnail').each(function () {
            this.addEventListener("mouseover", function (x) {
                let thumb_url = x.currentTarget.getAttribute('src').replace('&scale=true', '&scale=false');
                const tooltip = document.createElement('div');
                tooltip.className = 'ui file-listing tooltip';
                let img = document.createElement('img');
                img.src = thumb_url;
                tooltip.appendChild(img);
                tooltip.style.top = (x.currentTarget.getBoundingClientRect().top + window.scrollY) + 'px';
                tooltip.style.left = (x.currentTarget.getBoundingClientRect().right + window.scrollX + 10) + 'px';
                x.currentTarget.parentElement.appendChild(tooltip);
            });
        });
        $('.file-listing.thumbnail').each(function () {
            this.addEventListener("mouseout", function (x) {
                let tooltip = $('.ui.file-listing.tooltip')[0];
                x.currentTarget.parentElement.removeChild(tooltip);
            });
        });
    });
})();