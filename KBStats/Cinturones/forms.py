from django import forms


class AddPartidaForm(forms.Form):
    match_id = forms.CharField(label='Match ID', required=True, widget=forms.TextInput(attrs={'class':'form-control'}))
    jornada = forms.CharField(label='Jornada', required=True, widget=forms.TextInput(attrs={'class':'form-control'}))
    numero_partida = forms.CharField(label='Número de partida', required=True, widget=forms.TextInput(attrs={'class':'form-control'}))
    equipo_azul = forms.CharField(label='Equipo Azul', required=True, widget=forms.TextInput(attrs={'class':'form-control'}))
    equipo_rojo = forms.CharField(label='Equipo Rojo', required=True, widget=forms.TextInput(attrs={'class':'form-control'}))
