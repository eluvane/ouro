// biome-ignore lint/nursery/noRestrictedDependencies: JQHTML boots through jQuery
// biome-ignore lint/style/useNamingConvention: $ is the jQuery binding JQHTML init expects
import $ from 'jquery/dist/jquery.slim.js';
import { boot, init, register } from '@jqhtml/core';

import './styles.css';

let mode = 'development';
if (import.meta.env.PROD) {
  mode = 'production';
}

init($, {
  mode,
});

const app = document.querySelector('#app');
const page = document.documentElement;

page.classList.add('is-loading');

try {
  const component_name = app?.dataset.componentInitName;
  let entry;

  if (component_name === 'Documentation_App') {
    entry = await import('./components/documentation_app.js');
  } else if (component_name === 'Site_App') {
    entry = await import('./components/site_app.js');
  } else {
    let label = 'missing';
    if (component_name !== undefined && component_name.length > 0) {
      label = component_name;
    }
    throw new Error(`Unknown entry component: ${label}`);
  }

  entry.components.forEach(register);
  await boot();
  await document.fonts.ready;
} catch {
  if (app !== null) {
    app.textContent = 'The page could not start. Check the browser console for details.';
  }
} finally {
  page.classList.remove('is-loading');
}
