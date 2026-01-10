(function () {
  function initTinyMCE() {
    if (!window.tinymce) return;

    const textarea = document.querySelector("#description");
    if (!textarea) {
      return;
    }

    const existing = tinymce.get(textarea.id);
    // Prevent double-init

    tinymce.init({
      selector: "#description",
      menubar: false,
      height: 300,
      setup(editor) {
        editor.on("change keyup", () => {
          editor.save(); // syncs content back to textarea
        });
      },
    });
  }

  // Run on initial load
  document.addEventListener("DOMContentLoaded", initTinyMCE);

  // Watch for FastAdmin DOM swaps
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.addedNodes.length) {
        initTinyMCE();
      }
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
})();
