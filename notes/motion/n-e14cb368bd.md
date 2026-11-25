---
id: n-e14cb368bd
kind: note
at: 2026-10-28T23:47:09Z
source: agent
---

Compile-checking Unity editor C# outside Unity with Roslyn csc (Editor/Data/DotNetSdk/dotnet.exe + sdk/*/Roslyn/bincore/csc.dll): reference Managed/UnityEngine/*.dll + NetStandard/ref/2.1.0/netstandard.dll but NOT Managed/UnityEditor.dll, else CS0433 'EditorApplication exists in both UnityEditor.CoreModule and UnityEditor'.
