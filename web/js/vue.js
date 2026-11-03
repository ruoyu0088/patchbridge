const Vue = window.Vue;

if (!Vue) {
  throw new Error('Vue runtime is missing: /static/vendor/vue.global.prod.js');
}

export const reactive = Vue.reactive;
export const createApp = Vue.createApp;
export const computed = Vue.computed;
