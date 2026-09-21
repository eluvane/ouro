// biome-ignore lint/nursery/noRestrictedDependencies: JQHTML boots through jQuery
// biome-ignore lint/style/useNamingConvention: $ is the jQuery binding JQHTML init expects
import $ from 'jquery/dist/jquery.slim.js';
import { Jqhtml_Component } from '@jqhtml/core';

import '../docs.css';
import '../docs-layout.css';
import '../docs-content.css';
import '../docs-code.css';
import '../docs-mobile.css';
import { site_config } from '../site.config.js';
import { highlight_search } from '../docs-enhancements.js';
import { DocumentationDetails } from '../docs-details.js';
import { DocumentationNavigation } from '../docs-navigation.js';
import DocumentationAppTemplate from './documentation_app.jqhtml';
import FeatureReferenceTemplate from './feature_reference.jqhtml';
import ProjectIntroductionTemplate from './project_introduction.jqhtml';
import QuickStartGuideTemplate from './quick_start_guide.jqhtml';

const SCROLL_BOTTOM_THRESHOLD_PX = 60;
const EMPTY_QUERY_LENGTH = 0;
const SINGLE_SECTION_COUNT = 1;
const OBSERVER_THRESHOLD = 0;

class DocumentationApp extends Jqhtml_Component {
  static component_name = 'Documentation_App';

  on_create() {
    this.args.site = site_config;
    this.observer = null;
    this.current_active_hash = '';
  }

  on_ready() {
    this.search_sections = this.$.find('[data-search-section]').toArray().map(
      (element) => ({ element, text: element.textContent.toLowerCase() }),
    );
    this.sync_active_link();
    this.setup_scrollspy();
    this.details = new DocumentationDetails(this.$);
    this.navigation = new DocumentationNavigation(this.$[0], this.$sid('menu_toggle')[0]);

    $(document).on('keydown.docs', (event) => this.handle_shortcut(event));
    $(globalThis).on('hashchange.docs', () => this.sync_active_link());
  }

  on_stop() {
    this.navigation?.stop();
    if (this.observer) {
      this.observer.disconnect();
      this.observer = null;
    }
    this.details?.stop();
    $(document).off('.docs');
    $(globalThis).off('.docs');
  }

  setup_scrollspy() {
    if (!('IntersectionObserver' in globalThis)) {
      return;
    }

    const section_elements = this.$.find('[id]').filter(
      '#introduction, .docs-section',
    );
    if (section_elements.length === 0) {
      return;
    }

    const section_order = [];
    section_elements.each((_, elem) => {
      if (elem.id) {
        section_order.push(elem.id);
      }
    });

    const visible_set = new Set();

    const handle_intersect = (entries) => {
      for (const entry of entries) {
        const { id } = entry.target;
        if (entry.isIntersecting) {
          visible_set.add(id);
        } else {
          visible_set.delete(id);
        }
      }

      const doc_elem = document.documentElement;
      const scroll_top = doc_elem.scrollTop || document.body.scrollTop;
      const scroll_height = doc_elem.scrollHeight || document.body.scrollHeight;
      const client_height = doc_elem.clientHeight;

      if (
        scroll_height - scroll_top - client_height <=
        SCROLL_BOTTOM_THRESHOLD_PX
      ) {
        const last_id = section_order.at(-SINGLE_SECTION_COUNT);
        if (last_id) {
          this.set_active_link(`#${last_id}`);
          return;
        }
      }

      for (const id of section_order) {
        if (visible_set.has(id)) {
          this.set_active_link(`#${id}`);
          return;
        }
      }
    };

    this.observer = new globalThis.IntersectionObserver(handle_intersect, {
      root: null,
      rootMargin: '-80px 0px -60% 0px',
      threshold: OBSERVER_THRESHOLD,
    });

    section_elements.each((_, elem) => {
      this.observer?.observe(elem);
    });
  }

  set_active_link(target_hash) {
    if (this.current_active_hash === target_hash) {
      return;
    }
    this.current_active_hash = target_hash;
    const links = this.$.find('[data-nav-link]');
    links.removeClass('is-active').removeAttr('aria-current');
    const active_link = links.filter(`[href="${target_hash}"]`);
    active_link.addClass('is-active').attr('aria-current', 'page');
  }

  toggle_navigation() {
    if (!this.navigation.is_open()) {
      this.close_search();
    }
    this.navigation.toggle();
  }

  close_navigation(event) {
    this.navigation.close(event);
  }

  open_search() {
    this.close_navigation();
    this.$.addClass('search-open');
    this.$sid('search_toggle').attr('aria-expanded', 'true').attr('aria-label', 'Close search');
    this.$sid('search_input').trigger('focus');
  }

  close_search() {
    this.$.removeClass('search-open');
    this.$sid('search_toggle').attr('aria-expanded', 'false').attr('aria-label', 'Open search');
  }

  toggle_search() {
    if (this.$.hasClass('search-open')) {
      this.clear_search();
      this.close_search();
      this.$sid('search_toggle').trigger('focus');
    } else {
      this.open_search();
    }
  }

  clear_search() {
    this.$sid('search_input').val('');
    this.apply_search('');
  }

  search_docs(event) {
    this.apply_search(event.currentTarget.value);
  }

  apply_search(raw_query) {
    const query = raw_query.trim().toLowerCase();
    this.$.toggleClass('is-searching', query.length > EMPTY_QUERY_LENGTH);
    let visible_count = 0;

    for (const { element, text } of this.search_sections) {
      const is_visible =
        query.length === EMPTY_QUERY_LENGTH || text.includes(query);
      element.hidden = !is_visible;
      element.classList.toggle(
        'is-first-search-result',
        is_visible && visible_count === 0 && query.length > EMPTY_QUERY_LENGTH,
      );
      let highlight_query = '';
      if (is_visible) {
        highlight_query = raw_query.trim();
      }
      highlight_search(element, highlight_query);
      visible_count += is_visible;
    }

    this.$.find('[data-search-link]').each((_, link) => {
      const target = document.querySelector(`#${CSS.escape(link.hash.slice(1))}`);
      $(link).prop('hidden', !target || target.hidden);
    });

    let status = '';
    if (query.length > EMPTY_QUERY_LENGTH) {
      let noun = 'sections';
      if (visible_count === SINGLE_SECTION_COUNT) {
        noun = 'section';
      }
      status = `${visible_count} ${noun}`;
    }

    this.$sid('empty_state').prop(
      'hidden',
      query.length === EMPTY_QUERY_LENGTH || visible_count > 0,
    );
    this.$sid('search_status').text(status);
    if (query.length > EMPTY_QUERY_LENGTH) {
      globalThis.scrollTo({ top: 0, behavior: 'instant' });
    }
  }

  handle_shortcut(event) {
    if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    const is_editing = event.target instanceof HTMLElement && (
      event.target.isContentEditable || event.target.closest('input, textarea, select')
    );
    if (event.key === '/' && !is_editing) {
      event.preventDefault();
      this.open_search();
    }

    if (event.key === 'Escape') {
      const search_was_open = this.$.hasClass('search-open');
      this.clear_search();
      this.close_search();
      this.close_navigation();
      if (search_was_open && this.$sid('search_toggle').is(':visible')) {
        this.$sid('search_toggle').trigger('focus');
      }
    }
  }

  sync_active_link() {
    let current_hash = globalThis.location.hash;
    if (current_hash.length === EMPTY_QUERY_LENGTH) {
      current_hash = '#introduction';
    }
    this.set_active_link(current_hash);
  }
}

export const components = [
  FeatureReferenceTemplate,
  ProjectIntroductionTemplate,
  QuickStartGuideTemplate,
  DocumentationAppTemplate,
  DocumentationApp,
];
