const form = document.querySelector("form");

if (form) {
  console.log(form);
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (typeof tinymce !== "undefined") {
      // Get the content and explicitly save it back to the original textarea
      tinymce.triggerSave();
    }
  });
}
