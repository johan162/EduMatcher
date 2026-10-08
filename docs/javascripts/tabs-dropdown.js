// Positions each .md-tabs__dropdown (see overrides/partials/tabs-item.html)
// under its tab. CSS alone shows/hides it via :hover/:focus-within; this
// only sets position:fixed's top/left, which can't be expressed relative to
// the triggering tab in plain CSS.
document.querySelectorAll(".md-tabs__item--group").forEach(function (group) {
  var dropdown = group.querySelector(".md-tabs__dropdown");
  if (!dropdown) return;
  var place = function () {
    var rect = group.getBoundingClientRect();
    dropdown.style.top = rect.bottom + "px";
    dropdown.style.left = rect.left + "px";
  };
  group.addEventListener("mouseenter", place);
  group.addEventListener("focusin", place);
});
