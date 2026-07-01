// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import type { PageLoad } from "./$types";

// All data is fetched at runtime over the JS<->Python bridge (see
// LsatHomePage.svelte), so there is nothing to load up front.
export const load = (async () => {
    return {};
}) satisfies PageLoad;
