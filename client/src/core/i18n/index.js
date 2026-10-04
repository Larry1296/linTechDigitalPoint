import { useSyncExternalStore } from 'react';
const catalog = {
  en: { receive:'Receive stock', expenses:'Money spent', reports:'Accounting reports', sale:'Point of Sale', quantity:'Quantity received', cost:'Buying price for one', category:'Category', amount:'Amount', recordExpense:'Record expense' },
  sw: { receive:'Pokea bidhaa', expenses:'Matumizi ya pesa', reports:'Ripoti za hesabu', sale:'Uuzaji', quantity:'Idadi iliyopokelewa', cost:'Bei ya kununua moja', category:'Aina', amount:'Kiasi', recordExpense:'Rekodi matumizi' },
};
function language() { try { return localStorage.getItem('lintech-language') === 'sw' ? 'sw' : 'en'; } catch { return 'en'; } }
function subscribe(listener) {
  window.addEventListener('language-changed',listener);window.addEventListener('storage',listener);
  return ()=>{window.removeEventListener('language-changed',listener);window.removeEventListener('storage',listener);};
}
export function setLanguage(value) { try { localStorage.setItem('lintech-language',value==='sw'?'sw':'en'); } catch { /* Preference persistence is optional. */ } window.dispatchEvent(new Event('language-changed')); }
export function useTranslation() {
  const locale=useSyncExternalStore(subscribe,language,()=> 'en');
  return {locale,t:key=>catalog[locale][key]||catalog.en[key]||key};
}
