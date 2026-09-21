// biome-ignore lint/nursery/noRestrictedDependencies: JQHTML boots through jQuery
// biome-ignore lint/style/useNamingConvention: $ is the jQuery binding JQHTML init expects
import $ from 'jquery/dist/jquery.slim.js';
import { copy_text, highlight_code } from './docs-enhancements.js';

const COPY_RESET_DELAY_MS = 1800;

class DocumentationDetails {
  constructor(root) {
    this.$ = root;
    this.copy_timers = new Map();
    this.is_stopped = false;
    this.setup_code_copy();
    this.setup_heading_links();
  }

  stop() {
    this.is_stopped = true;
    for (const timer of this.copy_timers.values()) {
      globalThis.clearTimeout(timer);
    }
    this.copy_timers.clear();
    this.$.off('.code_copy').off('.heading_links');
  }

  setup_code_copy() {
    this.$.find('.docs-code').each((_, code_elem) => {
      const pre_block = $(code_elem);
      if (pre_block.parent().hasClass('docs-example')) {
        return;
      }
      const code = code_elem.querySelector('code');
      if (!code) {
        return;
      }
      const language = code_elem.dataset.language || 'ouro';
      highlight_code(code, language);
      pre_block.wrap('<div class="docs-example"></div>');
      const toolbar = $('<div class="docs-code__toolbar" data-search-ignore></div>');
      let label = 'example.ouro';
      if (language === 'terminal') {
        label = 'terminal';
      }
      $('<span class="docs-code__label"></span>').text(label).appendTo(toolbar);
      const copy_btn = $(
        '<button type="button" class="docs-code__copy" aria-label="Copy code" title="Copy code">' +
        '<span class="site-icon site-icon--copy" aria-hidden="true"></span></button>',
      );
      toolbar.append(copy_btn);
      pre_block.before(toolbar);
    });

    this.$.on('click.code_copy', '.docs-code__copy', async (event) => {
      event.preventDefault();
      const clicked_btn = $(event.currentTarget);
      if (clicked_btn.attr('aria-busy') === 'true') {
        return;
      }
      const code = clicked_btn.closest('.docs-example').find('code');
      this.reset_copy_button(clicked_btn);
      clicked_btn.attr('aria-busy', 'true');
      try {
        await copy_text(code.text());
        if (this.is_stopped) {
          return;
        }
        clicked_btn.addClass('is-copied').attr('aria-label', 'Code copied');
        this.copy_timers.set(event.currentTarget, globalThis.setTimeout(
          () => this.reset_copy_button(clicked_btn), COPY_RESET_DELAY_MS,
        ));
      } catch {
        if (!this.is_stopped) {
          clicked_btn.addClass('is-error').attr('aria-label', 'Copy failed. Retry copying code');
        }
      } finally {
        clicked_btn.removeAttr('aria-busy');
      }
    });
  }

  reset_copy_button(button) {
    globalThis.clearTimeout(this.copy_timers.get(button[0]));
    this.copy_timers.delete(button[0]);
    button.removeClass('is-copied is-error').attr('aria-label', 'Copy code');
  }

  setup_heading_links() {
    this.$.find('.docs-section').each((_, section) => {
      const heading = section.querySelector('h2');
      if (!heading || heading.querySelector('.heading-anchor')) {
        return;
      }
      const link = document.createElement('a');
      link.className = 'heading-anchor';
      link.href = `#${section.id}`;
      link.dataset.searchIgnore = '';
      const icon = document.createElement('span');
      icon.className = 'site-icon site-icon--link';
      icon.setAttribute('aria-hidden', 'true');
      link.append(icon);
      const title = heading.textContent.trim();
      link.setAttribute('aria-label', `Copy link to ${title}`);
      link.title = 'Copy section link';
      heading.append(link);
    });
    this.$.on('click.heading_links', '.heading-anchor', async (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const link = $(event.currentTarget);
      try {
        await copy_text(event.currentTarget.href);
        if (!this.is_stopped) {
          link.removeClass('is-error').attr('title', 'Copy section link');
        }
      } catch {
        if (!this.is_stopped) {
          link.addClass('is-error').attr('title', 'Copy failed. Copy the URL from your address bar.');
        }
      }
    });
  }

}

export { DocumentationDetails };
