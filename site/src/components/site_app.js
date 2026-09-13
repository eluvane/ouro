import { Jqhtml_Component } from '@jqhtml/core';

import { site_config } from '../site.config.js';
import { TypePlay } from '../type-play.js';
import '../type-play.css';
import SiteAppTemplate from './site_app.jqhtml';

class SiteApp extends Jqhtml_Component {
  static component_name = 'Site_App';

  on_create() {
    this.args.site = site_config;
  }

  on_ready() {
    this.type_play = new TypePlay(this.$.find('.site-intro')[0]);
  }

  on_stop() {
    this.type_play?.stop();
  }
}

export const components = [SiteAppTemplate, SiteApp];
