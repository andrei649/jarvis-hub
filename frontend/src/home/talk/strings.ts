/* The conversation register's words (PHASE_B_PLAN.md §5.3), in English and Romanian.

   Every user-visible string the Phase B conversation code writes comes from this pair of tables;
   home/talk/strings.test.ts asserts it is complete (frame/strings.ts stringProblems). Copy that
   the legacy composer and transcript already showed (the composer's own hints, the dialogs'
   labels, `V2.I18N` keys) stays where it is: these tables hold only what the re-lay adds.

   Kinds become words only through these fixed tables (the routing policy, the approval mode,
   the tool states, where a reply ran), never through generated copy. */
import React from 'react';
import { defineStrings, langOf, pick, type Lang } from '../../frame/strings';

export const TALK_STRINGS = defineStrings({
  en: {
    // ---- the register head ----------------------------------------------------------------
    title: 'Conversation',
    withAgent: 'with {agent}',
    withNone: 'no agent chosen',
    searchEarlier: 'Search earlier conversations',
    policyTitle: 'Declared policy before sending; actual model use appears after the reply.',
    policyOrchestrated: 'Orchestrated',
    policyLocal: 'Local',
    policyCloudOnly: 'Cloud only',
    policyCloudPreferred: 'Cloud preferred',
    policyClaudePreferred: 'Claude preferred',
    policyAuto: 'Auto',
    policyUnknown: 'Routing policy unknown',
    policyUnavailable: 'Unavailable',
    policyDemo: 'Demo sample',
    // the hub did not serve the agent roster: the policy is not known, which is not "unavailable"
    policyNotServed: 'The hub did not serve the agent roster, so the declared routing policy is not known.',

    // ---- the composer ----------------------------------------------------------------------
    composerLabel: 'Write to {agent}',
    // "Write to <Agent>": the Dossier's button, and the To's question once the reply has ended
    writeTo: 'Write to {agent}',
    to: 'To',
    toChoose: 'Choose an agent',
    // a change of recipient asked for while a reply is being written: it waits for the owner's answer
    switchWarn: 'Writing to {agent} stops the reply in progress.',
    switchConfirm: 'Stop it and write to {agent}',
    switchCancel: 'Keep writing to {current}',
    switchCancelNone: 'Let the reply finish',
    // …and once that reply has ended (finished or stopped), still unanswered: nothing switches by itself
    switchEnded: 'The reply from {current} has ended. Write to {agent}?',
    switchEndedNone: 'The reply has ended. Write to {agent}?',
    switchStay: 'Stay with {current}',
    switchStayNone: 'Not now',
    // …while the hub does not serve the roster: the question stays, and only its switch waits
    switchHeld: 'The hub did not serve the agent roster, so {agent} cannot be chosen until it does.',
    // …and dropped, because a roster the hub served no longer offers the agent asked for: said
    // until the next send, a change of recipient or Dismiss (Send is free: nothing waits on it)
    switchDropped: '{agent} is not available now, so the change to {agent} was dropped. Messages still go to {current}.',
    switchDroppedNone: '{agent} is not available now, so the change to {agent} was dropped.',
    dismiss: 'Dismiss',
    // the composer's line while there is no recipient to send to; the register head says the
    // same sentence, starting in lower case
    recipientChecking: 'Checking the selected agent…',
    // a poll has completed and the hub did not serve the roster: the selected agent is kept, and
    // confirmed once a served roster offers it; meanwhile nothing is sent to it, and the To offers
    // {fallback} (Jarvis, App's default, which needs no roster). Nothing switches by itself.
    recipientNotServed: 'The hub did not serve the agent roster, so {agent} cannot be confirmed until it does. Nothing is sent until then, unless you choose {fallback}.',
    // …the head ("with Frigga · not confirmed") and the To ("Frigga · not confirmed") say it short,
    // the head with the sentence above in its tooltip
    unconfirmed: 'not confirmed',
    toUnconfirmed: '{agent} · not confirmed',
    recipientChoose: 'Choose an available agent before sending.',
    // why there is no recipient (types.ts RecipientRefusal): never a substitute, so nothing is sent
    recipientUnavailable: '{agent} is not available now. Nothing is sent until you choose who to write to.',
    recipientSignIn: 'The sign-in changed, so the agent chosen before is not used. Nothing is sent until you choose who to write to.',
    recipientConversation: 'No agent is chosen for this conversation. Nothing is sent until you choose who to write to.',
    recipientUnverified: 'The agent chosen before could not be verified, so it is not used. Nothing is sent until you choose who to write to.',
    mode: 'Mode',
    modeAuto: 'Auto',
    modeAsk: 'Ask',
    modeOff: 'Off',
    modeAutoMeans: 'each action is decided by its risk tier',
    modeAskMeans: 'anything with a side effect waits for you',
    modeOffMeans: 'nothing a machine approved runs',
    modeAutoFull: 'Each action is decided by its risk tier: reads and reversible actions run, a payment inside your per-action and daily money caps runs, any other irreversible action asks.',
    modeAskFull: 'Anything with a side effect waits for your approval; an approval of a terminal command, a checkpoint operation, a browser step or a provider change takes effect only in Auto.',
    modeOffFull: 'Nothing a machine approved runs: every action waits for your approval and the proactive loop is paused.',
    modeUnknown: 'Mode unknown',
    modeNotRead: 'not read on this page',
    modeStale: 'checked {time}',
    modeOwn: '{agent}’s own setting',
    modeOwnTitle: '{agent} has its own approval mode, which applies instead of the global one.',
    placeholder: 'Message {agent}…',
    send: 'Send',
    attach: 'Attach',
    images: 'Images…',
    vaultNotes: 'Vault notes',
    vaultNeedsText: 'type a message first',
    voice: 'Voice',
    voiceLocalStt: 'speech-to-text on this machine',
    voiceMuted: 'mic muted',
    voiceUnsupported: 'not supported in this browser',
    options: 'Options',
    voiceSettings: 'Voice settings…',
    usePreviousImage: 'Use previous image',
    blenderOn: 'Editable Blender model is on for this message.',
    keysCommands: 'commands',
    keysFiles: 'files',
    keysTitle: '/new  /undo  /refine  /<skill>  @file:path',
    count: '{n} of {max} characters',
    whyVaultBusy: 'Looking up vault notes…',
    whyBoardBusy: 'Reading the task result…',
    whyBoardReview: 'Finish reviewing the task result first.',
    whyHistorySending: 'Sending with the chat passage…',
    whyBoardConsent: 'Allow the reviewed passages to reach the cloud provider, or remove them.',
    whyBlenderEmpty: 'Describe the model in the message field.',
    whyBlenderLong: 'The Blender instruction is over 4,096 characters.',
    whyBlenderCommand: 'A / command cannot make a Blender model. Remove the / or turn off the Blender model.',
    whyBlenderBlocked: 'Remove the attachment or turn off the Blender model.',
    whyHistoryText: 'Write a message to send with the chat passage.',
    whyImages: 'Finish the image review above.',
    whyOffice: 'Choose the document passage to send.',
    whyTooLong: { one: 'The message is {n} character over the limit of {max}.', few: 'The message is {n} characters over the limit of {max}.', other: 'The message is {n} characters over the limit of {max}.' },

    // ---- the transcript --------------------------------------------------------------------
    you: 'You',
    system: 'System',
    vision: 'Vision analysis',
    visionWho: 'Vision',
    imagesSent: 'Images: {names}',
    loopback: 'loopback',
    remote: 'remote',

    // ---- the working reply -----------------------------------------------------------------
    stepsLabel: 'Steps of this reply',
    stepSent: 'Sent',
    stepStarted: 'Started — asked {agent}',
    stepTools: 'Tools',
    stepWriting: 'Writing',
    stepDone: 'done',
    stepNow: 'in progress',
    stepTodo: 'to come',
    toolsLabel: 'Tools this reply is running',
    statusWaitStart: 'Waiting for {agent} to start…',
    statusRunning: 'Running {tool}…',
    statusRunningMore: { one: 'Running {tool} and 1 more…', few: 'Running {tool} and {n} more…', other: 'Running {tool} and {n} more…' },
    statusCalling: 'Calling {tool}…',
    statusWriting: { one: 'Writing — {n} word so far', few: 'Writing — {n} words so far', other: 'Writing — {n} words so far' },
    statusFirstWords: 'Started — waiting for the first words…',
    statusAnswer: 'Waiting for your answer',
    statusPending: 'Waiting for the reply…',
    metaAsked: 'asked {time} · {elapsed} so far',
    elapsedSeconds: '{n} s',
    elapsedMinutes: '{n} min',
    elapsedHours: '{h} h {m} min',
    whereLater: 'where it runs is reported when the reply ends',
    whereModel: 'model {model} (reported)',
    stopOne: 'Stop this reply',
    stopMany: 'Stop the replies',
    toolRequested: 'requested',
    toolRunning: 'running',
    toolDone: 'done',
    toolFailed: 'failed',
    toolStopped: 'stopped by the loop guard',

    // ---- the reply footnote ----------------------------------------------------------------
    footnoteLabel: 'Where this reply ran and what it called',
    allPairs: { one: 'Show the model call', few: 'Show all {n} model calls', other: 'Show all {n} model calls' },
    whereTitle: 'By route: where the hub sent the prompt, not where the model computed.',
    toolCalls: { one: '{n} tool call', few: '{n} tool calls', other: '{n} tool calls' },

    // ---- reply actions ---------------------------------------------------------------------
    actionsLabel: 'Actions for this reply',
    ownerActionsLabel: 'Actions for your message',
    copy: 'Copy',
    copied: 'Copied',
    copyFailed: 'Copy failed',
    readAloud: 'Read aloud',
    reading: 'Reading…',
    readFailed: 'Read aloud unavailable',
    createTask: 'Create task',
    more: 'More',
    moreReply: 'More actions for this reply',
    moreOwner: 'More actions for your message',
    remember: 'Remember message',
    findSavedSource: 'Find saved source',
    sourcePhrase: 'Exact phrase from this reply',
    sourcePhraseInvalid: 'Choose an exact phrase from this reply.',
    sourceMatching: 'Matching saved facts',
    sourceCaveat: 'These are matching saved facts. They do not prove that the model used a fact in this reply.',
    sourceNone: 'No matching saved facts.',
    sourceLoading: 'Loading saved facts…',
    sourceUnavailable: 'Saved facts unavailable. Try again later.',
    sourceManual: 'Source: saved fact · {store}',
    sourceNotes: 'Agent notes',
    sourceProfile: 'User profile',
    sourceOpen: 'Open original',
    sourceOpening: 'Opening original…',
    sourceChanged: 'The original changed or cannot be verified.',
    sourceReadError: 'Could not read the original. Try again.',
    sourceOriginal: 'Verified original message',
    sourceOwnerOnly: 'Owner access is required to view saved facts.',
    sourceClose: 'Close',
    saveObsidian: 'Save to Obsidian',
    teach: 'Teach skill',
    reviewBlender: 'Review Blender model',
    turnDetails: 'Turn details',
    turnDetailsEmpty: 'No turn details were reported.',

    // ---- the approval slip -----------------------------------------------------------------
    slipHead: { one: '{n} action waits for your decision', few: '{n} actions wait for your decision', other: '{n} actions wait for your decision' },
    slipRequest: 'Request {id}',
    onDocket: 'On the docket',
    notOnDocket: 'not on the docket',
    docketChecking: 'checking the docket…',
    docketUnknown: 'the docket did not answer',
    docketRefused: 'the docket needs the owner credential',
    docketDemo: 'demo sample',
    openInDecisions: 'Open in Decisions',
    slipMainWindow: 'Decide in the main window.',
    openInApp: 'Open in app',
    handoffFailed: 'The main window did not open:',
  },
  ro: {
    title: 'Conversație',
    withAgent: 'cu {agent}',
    withNone: 'niciun agent ales',
    searchEarlier: 'Caută în conversațiile anterioare',
    policyTitle: 'Politica declarată înainte de trimitere; modelul folosit se vede după răspuns.',
    policyOrchestrated: 'Orchestrat',
    policyLocal: 'Local',
    policyCloudOnly: 'Doar cloud',
    policyCloudPreferred: 'Preferă cloud',
    policyClaudePreferred: 'Preferă Claude',
    policyAuto: 'Automat',
    policyUnknown: 'Politica de rutare necunoscută',
    policyUnavailable: 'Indisponibil',
    policyDemo: 'Mostră demo',
    policyNotServed: 'Hubul nu a trimis lista agenților, așa că politica de rutare declarată nu se cunoaște.',

    composerLabel: 'Scrie-i lui {agent}',
    writeTo: 'Scrie-i lui {agent}',
    to: 'Către',
    toChoose: 'Alege un agent',
    switchWarn: 'Dacă îi scrii lui {agent}, răspunsul în curs se oprește.',
    switchConfirm: 'Oprește-l și scrie-i lui {agent}',
    switchCancel: 'Rămâi la {current}',
    switchCancelNone: 'Lasă răspunsul să se termine',
    switchEnded: 'Răspunsul lui {current} s-a încheiat. Îi scrii lui {agent}?',
    switchEndedNone: 'Răspunsul s-a încheiat. Îi scrii lui {agent}?',
    switchStay: 'Rămâi la {current}',
    switchStayNone: 'Nu acum',
    switchHeld: 'Hubul nu a trimis lista agenților, așa că agentul {agent} nu poate fi ales până nu o trimite.',
    switchDropped: 'Agentul {agent} nu este disponibil acum, așa că schimbarea către {agent} a fost anulată. Mesajele merg în continuare către {current}.',
    switchDroppedNone: 'Agentul {agent} nu este disponibil acum, așa că schimbarea către {agent} a fost anulată.',
    dismiss: 'Închide',
    recipientChecking: 'Se verifică agentul selectat…',
    recipientNotServed: 'Hubul nu a trimis lista agenților, așa că agentul {agent} nu poate fi confirmat până nu o trimite. Nu se trimite nimic până atunci, decât dacă îl alegi pe {fallback}.',
    unconfirmed: 'neconfirmat',
    toUnconfirmed: '{agent} · neconfirmat',
    recipientChoose: 'Alege un agent disponibil înainte de a trimite.',
    recipientUnavailable: 'Agentul {agent} nu este disponibil acum. Nu se trimite nimic până nu alegi cui îi scrii.',
    recipientSignIn: 'Autentificarea s-a schimbat, așa că agentul ales înainte nu mai este folosit. Nu se trimite nimic până nu alegi cui îi scrii.',
    recipientConversation: 'Pentru această conversație nu este ales niciun agent. Nu se trimite nimic până nu alegi cui îi scrii.',
    recipientUnverified: 'Agentul ales înainte nu a putut fi verificat, așa că nu este folosit. Nu se trimite nimic până nu alegi cui îi scrii.',
    mode: 'Mod',
    modeAuto: 'Auto',
    modeAsk: 'Întreabă',
    modeOff: 'Oprit',
    modeAutoMeans: 'fiecare acțiune e decisă după nivelul ei de risc',
    modeAskMeans: 'orice acțiune cu efecte te așteaptă pe tine',
    modeOffMeans: 'nu rulează nimic aprobat de o mașină',
    modeAutoFull: 'Fiecare acțiune e decisă după nivelul ei de risc: citirile și acțiunile reversibile rulează, o plată în limitele tale pe acțiune și pe zi rulează, orice altă acțiune ireversibilă întreabă.',
    modeAskFull: 'Orice acțiune cu efecte așteaptă aprobarea ta; aprobarea unei comenzi de terminal, a unei operații de checkpoint, a unui pas de browser sau a unei schimbări de furnizor are efect doar în Auto.',
    modeOffFull: 'Nu rulează nimic aprobat de o mașină: fiecare acțiune așteaptă aprobarea ta, iar bucla proactivă e în pauză.',
    modeUnknown: 'Mod necunoscut',
    modeNotRead: 'necitit pe această pagină',
    modeStale: 'actualizat la {time}',
    modeOwn: 'setare proprie pentru {agent}',
    modeOwnTitle: '{agent} are propriul mod de aprobare, care se aplică în locul celui global.',
    placeholder: 'Mesaj către {agent}…',
    send: 'Trimite',
    attach: 'Atașează',
    images: 'Imagini…',
    vaultNotes: 'Note din seif',
    vaultNeedsText: 'scrie mai întâi un mesaj',
    voice: 'Voce',
    voiceLocalStt: 'transcriere pe acest calculator',
    voiceMuted: 'microfon oprit',
    voiceUnsupported: 'nu e suportată în acest browser',
    options: 'Opțiuni',
    voiceSettings: 'Setări voce…',
    usePreviousImage: 'Folosește imaginea anterioară',
    blenderOn: 'Modelul Blender editabil e activ pentru acest mesaj.',
    keysCommands: 'comenzi',
    keysFiles: 'fișiere',
    keysTitle: '/new  /undo  /refine  /<abilitate>  @file:cale',
    count: '{n} din {max} caractere',
    whyVaultBusy: 'Se caută notele din seif…',
    whyBoardBusy: 'Se citește rezultatul sarcinii…',
    whyBoardReview: 'Termină mai întâi revizuirea rezultatului sarcinii.',
    whyHistorySending: 'Se trimite cu pasajul din conversație…',
    whyBoardConsent: 'Permite trimiterea pasajelor revizuite către furnizorul cloud sau elimină-le.',
    whyBlenderEmpty: 'Descrie modelul în câmpul de mesaj.',
    whyBlenderLong: 'Instrucțiunea Blender depășește 4.096 de caractere.',
    whyBlenderCommand: 'O comandă / nu poate crea un model Blender. Șterge / sau oprește modelul Blender.',
    whyBlenderBlocked: 'Elimină atașamentul sau oprește modelul Blender.',
    whyHistoryText: 'Scrie un mesaj pe care să-l trimiți cu pasajul din conversație.',
    whyImages: 'Termină verificarea imaginilor de mai sus.',
    whyOffice: 'Alege pasajul din document pe care îl trimiți.',
    whyTooLong: { one: 'Mesajul depășește limita de {max} cu {n} caracter.', few: 'Mesajul depășește limita de {max} cu {n} caractere.', other: 'Mesajul depășește limita de {max} cu {n} de caractere.' },

    you: 'Tu',
    system: 'Sistem',
    vision: 'Analiză de imagine',
    visionWho: 'Imagine',
    imagesSent: 'Imagini: {names}',
    loopback: 'loopback',
    remote: 'la distanță',

    stepsLabel: 'Pașii acestui răspuns',
    stepSent: 'Trimis',
    stepStarted: 'Început — l-ai întrebat pe {agent}',
    stepTools: 'Instrumente',
    stepWriting: 'Scriere',
    stepDone: 'gata',
    stepNow: 'în curs',
    stepTodo: 'urmează',
    toolsLabel: 'Instrumentele pe care le rulează acest răspuns',
    statusWaitStart: 'Se așteaptă ca {agent} să înceapă…',
    statusRunning: 'Rulează {tool}…',
    statusRunningMore: { one: 'Rulează {tool} și încă unul…', few: 'Rulează {tool} și încă {n}…', other: 'Rulează {tool} și încă {n}…' },
    statusCalling: 'Se apelează {tool}…',
    statusWriting: { one: 'Scrie — {n} cuvânt până acum', few: 'Scrie — {n} cuvinte până acum', other: 'Scrie — {n} de cuvinte până acum' },
    statusFirstWords: 'A început — se așteaptă primele cuvinte…',
    statusAnswer: 'Se așteaptă răspunsul tău',
    statusPending: 'Se așteaptă răspunsul…',
    metaAsked: 'întrebat la {time} · {elapsed} până acum',
    elapsedSeconds: '{n} s',
    elapsedMinutes: '{n} min',
    elapsedHours: '{h} h {m} min',
    whereLater: 'locul rulării se raportează când se termină răspunsul',
    whereModel: 'model {model} (raportat)',
    stopOne: 'Oprește acest răspuns',
    stopMany: 'Oprește răspunsurile',
    toolRequested: 'cerut',
    toolRunning: 'rulează',
    toolDone: 'gata',
    toolFailed: 'eșuat',
    toolStopped: 'oprit de protecția la bucle',

    footnoteLabel: 'Unde a rulat acest răspuns și ce a apelat',
    allPairs: { one: 'Arată apelul de model', few: 'Arată toate cele {n} apeluri de model', other: 'Arată toate cele {n} de apeluri de model' },
    whereTitle: 'După rută: unde a trimis hubul promptul, nu unde a calculat modelul.',
    toolCalls: { one: '{n} apel de instrument', few: '{n} apeluri de instrumente', other: '{n} de apeluri de instrumente' },

    actionsLabel: 'Acțiuni pentru acest răspuns',
    ownerActionsLabel: 'Acțiuni pentru mesajul tău',
    copy: 'Copiază',
    copied: 'Copiat',
    copyFailed: 'Copierea a eșuat',
    readAloud: 'Citește cu voce tare',
    reading: 'Se citește…',
    readFailed: 'Citirea cu voce tare nu e disponibilă',
    createTask: 'Creează sarcină',
    more: 'Mai mult',
    moreReply: 'Mai multe acțiuni pentru acest răspuns',
    moreOwner: 'Mai multe acțiuni pentru mesajul tău',
    remember: 'Ține minte mesajul',
    findSavedSource: 'Caută sursa salvată',
    sourcePhrase: 'Fragment exact din acest răspuns',
    sourcePhraseInvalid: 'Alege un fragment exact din acest răspuns.',
    sourceMatching: 'Fapte salvate care se potrivesc',
    sourceCaveat: 'Acestea sunt fapte salvate care se potrivesc. Nu dovedesc că modelul a folosit o faptă în acest răspuns.',
    sourceNone: 'Nicio faptă salvată nu se potrivește.',
    sourceLoading: 'Se încarcă faptele salvate…',
    sourceUnavailable: 'Faptele salvate nu sunt disponibile. Încearcă mai târziu.',
    sourceManual: 'Sursă: faptă salvată · {store}',
    sourceNotes: 'Notițele agentului',
    sourceProfile: 'Profilul utilizatorului',
    sourceOpen: 'Deschide originalul',
    sourceOpening: 'Se deschide originalul…',
    sourceChanged: 'Originalul s-a schimbat sau nu poate fi verificat.',
    sourceReadError: 'Originalul nu a putut fi citit. Încearcă din nou.',
    sourceOriginal: 'Mesajul original verificat',
    sourceOwnerOnly: 'Este necesar accesul proprietarului pentru a vedea faptele salvate.',
    sourceClose: 'Închide',
    saveObsidian: 'Salvează în Obsidian',
    teach: 'Învață abilitate',
    reviewBlender: 'Revizuiește modelul Blender',
    turnDetails: 'Detaliile răspunsului',
    turnDetailsEmpty: 'Nu s-au raportat detalii pentru acest răspuns.',

    slipHead: { one: '{n} acțiune așteaptă decizia ta', few: '{n} acțiuni așteaptă decizia ta', other: '{n} de acțiuni așteaptă decizia ta' },
    slipRequest: 'Cererea {id}',
    onDocket: 'În registrul de semnături',
    notOnDocket: 'nu e în registrul de semnături',
    docketChecking: 'se verifică registrul de semnături…',
    docketUnknown: 'registrul de semnături nu a răspuns',
    docketRefused: 'registrul de semnături cere credențialul proprietarului',
    docketDemo: 'mostră demo',
    openInDecisions: 'Deschide în Decizii',
    slipMainWindow: 'Decide în fereastra principală.',
    openInApp: 'Deschide în aplicație',
    handoffFailed: 'Fereastra principală nu s-a deschis:',
  },
});

export type TalkStrings = ReturnType<typeof talkStrings>;

/** The table for a language (anything but 'ro' reads English). */
export function talkStrings(lang: unknown) {
  return pick(TALK_STRINGS, lang);
}

/** A composer sentence as the register head says it after "Conversation": the same words, starting
 *  in lower case ("checking the selected agent…"), so the head and the composer never word one fact
 *  two ways. */
export function lowerFirst(text: string, lang: unknown): string {
  const first = text.codePointAt(0);
  if (first === undefined) return text;
  const letter = String.fromCodePoint(first);
  return letter.toLocaleLowerCase(langOf(lang) === 'ro' ? 'ro-RO' : 'en-US') + text.slice(letter.length);
}

/** Fill `{name}` placeholders with React nodes, so a name can be set in bold without
 *  concatenating translated fragments: the whole sentence stays one template. */
export function fill(template: string, values: Readonly<Record<string, React.ReactNode>>): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  template.replace(/\{(\w+)\}/g, (whole, name: string, at: number) => {
    if (at > last) out.push(template.slice(last, at));
    out.push(Object.prototype.hasOwnProperty.call(values, name)
      ? React.createElement(React.Fragment, { key: `f${key++}` }, values[name]) : whole);
    last = at + whole.length;
    return whole;
  });
  if (last < template.length) out.push(template.slice(last));
  return out;
}

/** The declared routing policy as words (chat-routing-policy.tsx keeps the same map for its label). */
export function policyWord(policy: unknown, s: ReturnType<typeof talkStrings>): string {
  switch (policy) {
    case 'orchestrated': return s.policyOrchestrated;
    case 'local': return s.policyLocal;
    case 'cloud_only': return s.policyCloudOnly;
    case 'cloud_preferred': return s.policyCloudPreferred;
    case 'claude_preferred': return s.policyClaudePreferred;
    case 'auto': return s.policyAuto;
    default: return s.policyUnknown;
  }
}

export type { Lang };
