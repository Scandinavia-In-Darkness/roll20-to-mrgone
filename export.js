on("chat:message", function(msg) {
    // Check whether the message starts with !export-cofd
    if (msg.type === "api" && msg.content.indexOf("!export-cofd") === 0) {
        if (!playerIsGM(msg.playerid)) return;

        // Split the command to see which number the user typed (e.g. !export-cofd 1)
        let parts = msg.content.split(" ");
        let batchNumber = parseInt(parts[1]);

        if (isNaN(batchNumber) || batchNumber < 1) {
            sendChat("System", "Enter a batch number! Example: !export-cofd 1");
            return;
        }

        // Setting: how many characters per batch
        let batchSize = 20;

        // Get ALL characters in alphabetical order so the order is always the same
        let allCharacters = findObjs({_type: "character"});
        allCharacters.sort((a, b) => a.get("name").localeCompare(b.get("name")));

        // Work out which characters belong in this batch
        let startIndex = (batchNumber - 1) * batchSize;
        let endIndex = startIndex + batchSize;
        let batchCharacters = allCharacters.slice(startIndex, endIndex);

        if (batchCharacters.length === 0) {
            sendChat("System", "Found no characters in Batch " + batchNumber + ". You have probably reached the end!");
            return;
        }

        sendChat("System", "Starting export of Batch " + batchNumber + " (" + batchCharacters.length + " characters)...");

        let exportData = [];

        batchCharacters.forEach(char => {
            let charData = { name: char.get("name"), attributes: {} };
            let attributes = findObjs({_type: "attribute", _characterid: char.get("id")});

            attributes.forEach(attr => {
                let name = attr.get("name");
                // Optional: skip empty fields to save even more memory/space
                let val = attr.get("current");
                if (val !== "" && val !== null && val !== undefined) {
                    charData.attributes[name] = val;
                }
            });
            exportData.push(charData);
        });

        // Write the result to the API log
        log("=== START EXPORT BATCH " + batchNumber + " ===");
        log(JSON.stringify(exportData));
        log("=== END EXPORT BATCH " + batchNumber + " ===");

        let totalBatches = Math.ceil(allCharacters.length / batchSize);
        sendChat("System", "Batch " + batchNumber + " done! There are " + totalBatches + " batches to fetch in total.");
    }
});
