// @category GeodeSDK
// Decompile Geometry Dash object property setup/save functions after Geode's
// SyncBromaScript has imported 2.2081 symbols into the current Ghidra program.

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;

import java.io.File;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class DumpGDPropertyFunctions extends GhidraScript {
    private static final Pattern SAVE_KEY = Pattern.compile("[,;:]\\s*(\\d{1,4})\\s*[,;:]");

    private static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\r", "\\r")
                .replace("\n", "\\n")
                .replace("\t", "\\t");
    }

    private static boolean wanted(Function f) {
        String n = f.getName(true);
        return n.endsWith("::customObjectSetup")
            || n.endsWith("::getSaveString")
            || n.endsWith("GameObject::createWithKey")
            || n.endsWith("GameObject::objectFromVector");
    }

    private static TreeSet<Long> pcodeSmallConstants(HighFunction hf) {
        TreeSet<Long> out = new TreeSet<>();
        if (hf == null) return out;
        Iterator<PcodeOpAST> it = hf.getPcodeOps();
        while (it.hasNext()) {
            PcodeOpAST op = it.next();
            for (int i = 0; i < op.getNumInputs(); i++) {
                Varnode v = op.getInput(i);
                if (v != null && v.isConstant()) {
                    long x = v.getOffset();
                    if (x >= 1 && x <= 1024) out.add(x);
                }
            }
        }
        return out;
    }

    public void run() throws Exception {
        String[] args = getScriptArgs();
        File outFile = args.length > 0 ? new File(args[0]) : askFile("Save GD property decompile dump", "Save");
        DecompInterface decomp = new DecompInterface();
        decomp.toggleCCode(true);
        decomp.toggleSyntaxTree(true);
        if (!decomp.openProgram(currentProgram)) {
            printerr("Unable to open current program in decompiler");
            return;
        }

        List<String> rows = new ArrayList<>();
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        for (Function f : functions) {
            if (monitor.isCancelled()) break;
            if (!wanted(f)) continue;
            println("Decompiling " + f.getName(true) + " @ " + f.getEntryPoint());
            DecompileResults res = decomp.decompileFunction(f, 120, monitor);
            String c = "";
            HighFunction hf = null;
            if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
                c = res.getDecompiledFunction().getC();
                hf = res.getHighFunction();
            }

            TreeSet<Integer> saveKeys = new TreeSet<>();
            Matcher sm = SAVE_KEY.matcher(c);
            while (sm.find()) {
                int k = Integer.parseInt(sm.group(1));
                if (k >= 1 && k <= 1024) saveKeys.add(k);
            }
            TreeSet<Long> constants = pcodeSmallConstants(hf);

            StringBuilder js = new StringBuilder();
            js.append("{");
            js.append("\"name\":\"").append(esc(f.getName(true))).append("\",");
            js.append("\"short_name\":\"").append(esc(f.getName())).append("\",");
            js.append("\"address\":\"").append(f.getEntryPoint()).append("\",");
            js.append("\"signature\":\"").append(esc(f.getSignature().getPrototypeString())).append("\",");
            js.append("\"save_string_key_candidates\":[");
            boolean first = true;
            for (int k : saveKeys) { if (!first) js.append(','); first = false; js.append(k); }
            js.append("],\"small_pcode_constants\":[");
            first = true;
            for (long k : constants) { if (!first) js.append(','); first = false; js.append(k); }
            js.append("],\"decompiled\":\"").append(esc(c)).append("\"}");
            rows.add(js.toString());
        }
        decomp.dispose();

        try (FileWriter w = new FileWriter(outFile)) {
            w.write("{\"format\":\"gmdtool-ghidra-dump-v1\",\"functions\":[\n");
            for (int i = 0; i < rows.size(); i++) {
                if (i != 0) w.write(",\n");
                w.write(rows.get(i));
            }
            w.write("\n]}\n");
        }
        println("Wrote " + rows.size() + " functions to " + outFile);
    }
}
