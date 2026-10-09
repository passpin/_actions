// @category GeodeSDK
// Headless pre-script: import version-specific Broma Windows RVAs and create
// parser/serializer functions before analysis, without requiring a GUI.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import com.google.gson.*;
import java.nio.file.Files;
import java.nio.file.Path;

public class ImportGDBromaFacts extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("Pass the extracted broma JSON path");
        JsonObject root = JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject();
        Address base = currentProgram.getImageBase();
        int labels = 0, functions = 0;
        for (var entry : root.getAsJsonObject("classes").entrySet()) {
            Namespace namespace = currentProgram.getSymbolTable().getNamespace(entry.getKey(), null);
            if (namespace == null) namespace = currentProgram.getSymbolTable().createNameSpace(null, entry.getKey(), SourceType.USER_DEFINED);
            JsonObject methods = entry.getValue().getAsJsonObject().getAsJsonObject("methods");
            for (var method : methods.entrySet()) {
                for (var value : method.getValue().getAsJsonArray()) {
                    JsonObject definition = value.getAsJsonObject();
                    if (!definition.has("win") || definition.get("win").isJsonNull()) continue;
                    String rva = definition.get("win").getAsString();
                    if (!rva.startsWith("0x")) continue;
                    Address address = base.add(Long.parseLong(rva.substring(2), 16));
                    if (!currentProgram.getMemory().contains(address)) continue;
                    String name = method.getKey();
                    if (name.equals("customObjectSetup") || name.equals("getSaveString") || name.equals("createWithKey") || name.equals("objectFromVector") || name.equals("create") || name.equals("init")) {
                        disassemble(address);
                        Function function = getFunctionAt(address);
                        if (function == null) function = createFunction(address, null);
                        if (function != null) {
                            for (var symbol : currentProgram.getSymbolTable().getSymbols(address)) {
                                if (symbol != function.getSymbol() && symbol.getName().equals(name) && symbol.getParentNamespace().equals(namespace)) symbol.delete();
                            }
                            function.getSymbol().setNameAndNamespace(name, namespace, SourceType.USER_DEFINED);
                            functions++;
                        }
                    } else {
                        try {
                            createLabel(address, name, namespace, true, SourceType.USER_DEFINED);
                            labels++;
                        } catch (ghidra.util.exception.DuplicateNameException duplicate) {
                            // The same Broma RVA may represent several inline aliases.
                        }
                    }
                }
            }
        }
        println("Imported Broma labels=" + labels + " targeted functions=" + functions);
    }
}
