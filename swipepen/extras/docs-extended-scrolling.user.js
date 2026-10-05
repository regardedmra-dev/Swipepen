// ==UserScript==
// @name         Docs Extended Scrolling (Firefox)
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Adds extra scroll space at the bottom of Google Docs
// @match        https://docs.google.com/document/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';
    function addPadding() {
        const pageContainer = document.querySelector('.kix-rotatingtilemanager');
        if (pageContainer) {
            pageContainer.style.paddingBottom = '90vh';
        }
    }
    // Run once and also after Docs finishes loading
    addPadding();
    setTimeout(addPadding, 2000);
    setTimeout(addPadding, 5000);
})();
