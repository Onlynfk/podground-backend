(function () {
  let currentTextarea = null;

  function setReactTextareaValue(textarea, value) {
    // 1️⃣ Update the actual DOM value

    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    ).set;

    nativeSetter.call(textarea, value);

    const tracker = textarea._valueTracker;
    if (tracker) {
      tracker.setValue(""); // force React diff
    }

    // 3️⃣ Dispatch a proper input event so React notices
    const event = new Event("input", { bubbles: true });
    textarea.dispatchEvent(event);
  }

  function initTinyMCE() {
    if (!window.tinymce) return;

    const textarea = document.querySelector("#content");

    if (!textarea) return;

    if (textarea === currentTextarea) {
      return;
    }

    currentTextarea = textarea;

    const existing = tinymce.get(textarea.id);

    if (existing) {
      tinymce.remove(existing);
    }

    tinymce.init({
      selector: "#content",
      menubar: "file edit view insert format tools table help",
      height: 300,
      toolbar:
        "undo redo | bold italic underline strikethrough | fontselect fontsizeselect formatselect | alignleft aligncenter alignright alignjustify | outdent indent |  numlist bullist checklist | forecolor backcolor casechange permanentpen formatpainter removeformat | pagebreak | charmap emoticons | fullscreen  preview save print | insertfile image media pageembed template link anchor codesample | a11ycheck ltr rtl | showcomments addcomment code typography",
      // Exclude powerpaste/advcode/typography (premium) to avoid API key errors.
      plugins:
        "advlist autolink lists link image charmap print preview anchor searchreplace visualblocks code fullscreen insertdatetime media table help wordcount spellchecker paste fullpage",
      valid_elements: "*[*]",
      extended_valid_elements: "*[*]",
      valid_children: "+body[style],+*[*]",
      verify_html: false,
      cleanup: false,
      forced_root_block: "",
      paste_as_text: false,
      convert_urls: false,
      setup(editor) {
        editor.on("change keyup", function () {
          const textarea = editor.getElement();
          const content = editor.getContent();

          const event = new Event("input", { bubbles: true });
          textarea.dispatchEvent(event);
          setReactTextareaValue(textarea, content);
        });
      },
    });
  }

  // Initial page load
  document.addEventListener("DOMContentLoaded", initTinyMCE);

  // SPA navigation / DOM replacement
  const observer = new MutationObserver(() => initTinyMCE());

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
})();
